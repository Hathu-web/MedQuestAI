"""Kiểm thử migration thật, giao dịch nhập ca và các liên kết chéo nguy hiểm."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from flask_migrate import upgrade, downgrade
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app import create_app
from app.extensions import db
from app.models import (User, Case, CaseVersion, RubricCriterion, SimulationSession,
                        Message, SessionEvent, Submission, Evaluation, EvaluationItem,
                        Evidence, AIOperation, AICall, AuditLog)
from app.models.common import utc_now
from app.services.account_service import create_admin
from app.services.case_service import load_package, import_packages, validate_package, CaseValidationError

ROOT = Path(__file__).resolve().parents[1]


class DatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.app = create_app("testing", instance_path=self.temp.name)
        self.context = self.app.app_context()
        self.context.push()
        self.addCleanup(self.cleanup)
        upgrade(directory=str(ROOT / "migrations"))
        self.admin = User(email_normalized="admin@example.test", display_name="Test admin",
                          password_hash="test-fixture-not-a-password", role="ADMIN", is_test_account=1)
        db.session.add(self.admin)
        db.session.commit()
        self.packages = [load_package(p) for p in sorted((ROOT / "data/cases").glob("*.json"))]
        import_packages(self.packages, self.admin.email_normalized)
        self.versions = db.session.scalars(db.select(CaseVersion).order_by(CaseVersion.id)).all()

    def cleanup(self):
        db.session.remove()
        db.engine.dispose()
        self.context.pop()
        self.temp.cleanup()

    def count(self, model):
        return db.session.scalar(db.select(db.func.count()).select_from(model))

    def session_row(self, version_index=0, key="start"):
        row = SimulationSession(user_id=self.admin.id, case_version_id=self.versions[version_index].id,
                                mode="TEST", state_json={"state_id":"S0"}, start_request_key=key,
                                start_input_hash="a" * 64)
        db.session.add(row)
        db.session.commit()
        return row

    def operation(self, session, key="op"):
        op = AIOperation(session_id=session.id, request_key=key, input_hash="a"*64,
                         kind="TURN", expected_state_version=0, input_payload_json={"text":"Câu hỏi"})
        db.session.add(op)
        db.session.commit()
        return op

    def evaluation(self, session):
        session.status = "COMPLETED"
        session.ended_at = utc_now()
        db.session.flush()
        db.session.add(Submission(session_id=session.id, summary_json={"information":"Mẫu"}, payload_hash="b"*64))
        db.session.flush()
        result = Evaluation(session_id=session.id, case_version_id=session.case_version_id,
                            evaluation_no=1, input_hash="c"*64)
        db.session.add(result)
        db.session.commit()
        return result

    def item(self, session, evaluation):
        criterion = db.session.scalar(db.select(RubricCriterion).where(RubricCriterion.case_version_id == session.case_version_id).order_by(RubricCriterion.id))
        item = EvaluationItem(evaluation_id=evaluation.id, criterion_id=criterion.id, session_id=session.id,
                              case_version_id=session.case_version_id, level="MISSED", points_x2=0, reason_text="Chưa có bằng chứng")
        db.session.add(item)
        db.session.commit()
        return item

    def rejected(self, row):
        db.session.add(row)
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_upgrade_idempotent_and_schema_matches_models(self):
        upgrade(directory=str(ROOT / "migrations"))
        self.assertEqual(set(inspect(db.engine).get_table_names()), set(db.metadata.tables) | {"alembic_version"})
        self.assertEqual(self.count(Case), 2)
        self.assertEqual(self.count(RubricCriterion), 16)
        self.assertEqual(db.session.execute(text("PRAGMA foreign_key_check")).all(), [])
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext
        with db.engine.connect() as connection:
            self.assertEqual(compare_metadata(MigrationContext.configure(connection), db.metadata), [])

    def test_downgrade_and_upgrade_on_disposable_database(self):
        db.session.remove()
        downgrade(directory=str(ROOT / "migrations"), revision="base")
        self.assertEqual(inspect(db.engine).get_table_names(), ["alembic_version"])
        upgrade(directory=str(ROOT / "migrations"))
        self.assertEqual(len(inspect(db.engine).get_table_names()), len(db.metadata.tables) + 1)

    def test_reimport_same_package_is_idempotent(self):
        count = self.count(AuditLog)
        import_packages(self.packages, self.admin.email_normalized)
        self.assertEqual(self.count(CaseVersion), 2)
        self.assertEqual(self.count(RubricCriterion), 16)
        self.assertEqual(self.count(AuditLog), count)

    def test_conflict_in_second_package_rolls_back_whole_batch(self):
        first = deepcopy(self.packages[0]); first["case_code"] = "NEW_CASE"
        conflict = deepcopy(self.packages[1]); conflict["title"] = "Changed content"
        with self.assertRaises(CaseValidationError):
            import_packages([first, conflict], self.admin.email_normalized)
        self.assertEqual(self.count(Case), 2)
        self.assertEqual(self.count(CaseVersion), 2)
        self.assertEqual(self.count(RubricCriterion), 16)

    def test_new_version_does_not_change_old_session(self):
        session = self.session_row()
        old_id = session.case_version_id
        package = deepcopy(self.packages[0]); package["version_no"] = 2
        package["title"] += " (bản nháp mới)"
        import_packages([package], self.admin.email_normalized)
        self.assertEqual(self.count(CaseVersion), 3)
        self.assertEqual(db.session.get(SimulationSession, session.id).case_version_id, old_id)
        session.case_version_id = self.versions[1].id
        with self.assertRaises(IntegrityError): db.session.commit()
        db.session.rollback()

    def test_validation_rejects_bad_schema_weights_refs_and_ambiguous_rules(self):
        variants=[]
        p=deepcopy(self.packages[0]);p["rubric"][0]["weight"]=16;variants.append(p)
        p=deepcopy(self.packages[0]);p["content"]["rules"][0]["to_state"]="MISSING";variants.append(p)
        p=deepcopy(self.packages[0]);p["content"]["facts"][0]["fact_id"]="F02";variants.append(p)
        p=deepcopy(self.packages[0]);p["content"]["rules"].append({**p["content"]["rules"][0],"rule_id":"DUP"});variants.append(p)
        p=deepcopy(self.packages[0]);p["content"]["patient"]["portrait_key"]="../../.env";variants.append(p)
        p=deepcopy(self.packages[0]);p["status"]="PUBLISHED";variants.append(p)
        p=deepcopy(self.packages[0]);p["demo_only"]=False;variants.append(p)
        for p in variants:
            with self.subTest(variant=variants.index(p)):
                with self.assertRaises(CaseValidationError): validate_package(p)

    def test_duplicate_json_keys_rejected(self):
        path=Path(self.temp.name)/"bad.json";path.write_text('{"schema_version":1,"schema_version":2}')
        with self.assertRaises(CaseValidationError): load_package(path)

    def test_admin_hash_normalization_and_no_implicit_promotion(self):
        password = "test-only-long-password"
        admin = create_admin("  OWNER@Example.test ", "Người thử", password)
        self.assertEqual(admin.email_normalized, "owner@example.test")
        self.assertNotEqual(admin.password_hash, password)
        self.assertTrue(admin.check_password(password))
        self.assertFalse(admin.check_password("wrong"))
        with self.assertRaises(ValueError): create_admin("OWNER@example.test", "Again", password)
        with self.assertRaises(ValueError): create_admin("short@example.test", "Test", "123")
        self.assertEqual(self.count(User), 2)

    def test_import_requires_active_admin(self):
        for role,status in [("STUDENT","ACTIVE"),("ADMIN","LOCKED")]:
            self.admin.role=role;self.admin.status=status;db.session.commit()
            with self.assertRaises(CaseValidationError): import_packages(self.packages, self.admin.email_normalized)

    def test_start_request_key_unique_and_turn_limit(self):
        s=self.session_row()
        duplicate=SimulationSession(user_id=s.user_id,case_version_id=s.case_version_id,state_json={},start_request_key=s.start_request_key,start_input_hash="b"*64)
        self.rejected(duplicate)
        s.turn_index=21
        with self.assertRaises(IntegrityError): db.session.commit()
        db.session.rollback()

    def test_message_operation_cannot_cross_sessions(self):
        first=self.session_row(key="first");second=self.session_row(key="second")
        op=self.operation(first)
        self.rejected(Message(session_id=second.id,operation_id=op.id,seq_no=1,sender="LEARNER",content_text="Wrong session"))
        db.session.add(Message(session_id=first.id,operation_id=op.id,seq_no=1,sender="LEARNER",content_text="Correct session"));db.session.commit()

    def test_evaluation_must_match_session_version(self):
        s=self.session_row();ev=self.evaluation(s)
        self.rejected(Evaluation(session_id=s.id,case_version_id=self.versions[1].id,evaluation_no=2,input_hash="a"*64))
        self.assertEqual(self.count(Evaluation),1)

    def test_item_must_match_criterion_version_and_session(self):
        s=self.session_row();ev=self.evaluation(s)
        wrong=db.session.scalar(db.select(RubricCriterion).where(RubricCriterion.case_version_id==self.versions[1].id))
        self.rejected(EvaluationItem(evaluation_id=ev.id,criterion_id=wrong.id,session_id=s.id,case_version_id=s.case_version_id,level="MISSED",points_x2=0,reason_text="Invalid"))
        other=self.session_row(key="other")
        valid=db.session.scalar(db.select(RubricCriterion).where(RubricCriterion.case_version_id==s.case_version_id))
        self.rejected(EvaluationItem(evaluation_id=ev.id,criterion_id=valid.id,session_id=other.id,case_version_id=s.case_version_id,level="MISSED",points_x2=0,reason_text="Invalid"))

    def test_evidence_rejects_cross_session_and_multiple_sources(self):
        s=self.session_row();other=self.session_row(key="other")
        msg=Message(session_id=other.id,seq_no=1,sender="PATIENT",content_text="Other opening")
        event=SessionEvent(session_id=other.id,request_key="action",event_code="EVENT",event_type="ACTION",before_state={},after_state={})
        db.session.add_all([msg,event]);db.session.commit()
        ev=self.evaluation(s);item=self.item(s,ev)
        self.rejected(Evidence(item_id=item.id,session_id=s.id,message_id=msg.id,quote_text="Other opening"))
        self.rejected(Evidence(item_id=item.id,session_id=s.id,event_id=event.id,quote_text="Other event"))
        self.rejected(Evidence(item_id=item.id,session_id=s.id,quote_text="No source"))
        self.rejected(Evidence(item_id=item.id,session_id=s.id,submission_session_id=s.id,message_id=msg.id,quote_text="Two sources"))
        self.evaluation(other)
        self.rejected(Evidence(item_id=item.id,session_id=s.id,submission_session_id=other.id,quote_text="Wrong submission"))
        db.session.add(Evidence(item_id=item.id,session_id=s.id,submission_session_id=s.id,field_path="information",quote_text="Mẫu",start_offset=0,end_offset=3));db.session.commit()
        self.assertEqual(self.count(Evidence),1)

    def test_assessment_cannot_point_to_another_session(self):
        s=self.session_row();other=self.session_row(key="other");ev=self.evaluation(s)
        self.rejected(AIOperation(session_id=other.id,evaluation_id=ev.id,kind="ASSESSMENT",request_key="assessment",input_hash="a"*64,expected_state_version=0,input_payload_json={}))

    def test_only_one_running_ai_operation_and_call_attempt_unique(self):
        s=self.session_row();a=self.operation(s,"first");b=self.operation(s,"second")
        a.status="RUNNING";db.session.commit();b.status="RUNNING"
        with self.assertRaises(IntegrityError): db.session.commit()
        db.session.rollback()
        db.session.add(AICall(operation_id=a.id,stage="INTENT",attempt_no=1,status="UNKNOWN",reserved_cost_microusd=100));db.session.commit()
        call=db.session.scalar(db.select(AICall));self.assertIsNone(call.actual_cost_microusd)
        self.rejected(AICall(operation_id=a.id,stage="INTENT",attempt_no=1))

    def test_submission_requires_completed_session_and_is_immutable(self):
        s=self.session_row()
        self.rejected(Submission(session_id=s.id,summary_json={},payload_hash="a"*64))
        self.evaluation(s)
        submission=db.session.get(Submission,s.id);submission.summary_json={"changed":True}
        with self.assertRaises(IntegrityError): db.session.commit()
        db.session.rollback()
        s.status="ACTIVE";s.ended_at=None
        with self.assertRaises(IntegrityError): db.session.commit()
        db.session.rollback()
        abandoned=self.session_row(key="abandoned");abandoned.status="ABANDONED";abandoned.ended_at=utc_now();db.session.commit()
        self.rejected(Submission(session_id=abandoned.id,summary_json={},payload_hash="a"*64))

    def test_only_valid_evaluation_has_score_and_item_score_uses_rubric(self):
        s=self.session_row();ev=self.evaluation(s);ev.total_points_x2=0
        with self.assertRaises(IntegrityError): db.session.commit()
        db.session.rollback()
        criterion=db.session.scalar(db.select(RubricCriterion).where(RubricCriterion.case_version_id==s.case_version_id))
        self.rejected(EvaluationItem(evaluation_id=ev.id,criterion_id=criterion.id,session_id=s.id,case_version_id=s.case_version_id,level="ACHIEVED",points_x2=1,reason_text="Wrong formula"))

    def test_approved_case_and_rubric_cannot_be_rewritten(self):
        v=self.versions[0];v.status="APPROVED";db.session.commit()
        v.title="Changed"
        with self.assertRaises(IntegrityError): db.session.commit()
        db.session.rollback()
        v.status="DRAFT"
        with self.assertRaises(IntegrityError): db.session.commit()
        db.session.rollback()
        criterion=db.session.scalar(db.select(RubricCriterion).where(RubricCriterion.case_version_id==v.id));criterion.weight=99
        with self.assertRaises(IntegrityError): db.session.commit()
        db.session.rollback()

    def test_demo_cannot_publish_and_only_one_published_version(self):
        v=self.versions[0];v.status="PUBLISHED"
        with self.assertRaises(IntegrityError): db.session.commit()
        db.session.rollback()
        p=deepcopy(self.packages[0]);p["version_no"]=2;import_packages([p],self.admin.email_normalized)
        # Direct writes only to isolate DB index; production publishing service is a later step.
        v.demo_only=0;v.status="PUBLISHED";db.session.commit()
        second=db.session.scalar(db.select(CaseVersion).where(CaseVersion.case_id==v.case_id,CaseVersion.version_no==2))
        second.demo_only=0;second.status="PUBLISHED"
        with self.assertRaises(IntegrityError): db.session.commit()
        db.session.rollback()

    def test_history_restricts_deleting_parent_user_and_case(self):
        db.session.delete(self.admin)
        with self.assertRaises(IntegrityError): db.session.commit()
        db.session.rollback()
        db.session.delete(self.versions[0].case)
        with self.assertRaises(IntegrityError): db.session.commit()
        db.session.rollback()

    def test_cli_reports_data_and_duplicate_admin_without_password_prompt(self):
        runner=self.app.test_cli_runner()
        for args in (["check","--db"],["validate-cases"],["list-cases"],["import-cases","--admin-email",self.admin.email_normalized],["create-admin","--email",self.admin.email_normalized]):
            result=runner.invoke(args=args)
            self.assertEqual(result.exit_code,0,result.output)
        self.assertEqual(self.count(User),1)


if __name__ == "__main__":
    unittest.main()
