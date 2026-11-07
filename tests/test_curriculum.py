"""Four-coursework-case release on disposable SQLite; no paid/network AI calls."""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from flask_migrate import upgrade
from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import db
from app.models import AuditLog, CaseVersion, Message, SimulationSession, User
from app.ai.chunking import case_documents, digest
from app.ai.embeddings import Embedder
from app.ai.errors import AIError
from app.ai.patient_dialogue import plan_patient_turn, retrieval_queries
from app.ai.settings import DEFAULTS
from app.ai.vectorstore import index_case, load_index
from app.services.case_service import CaseValidationError, import_packages, load_package, validate_package
from app.services.catalog_service import (bundle_versions, curriculum_packages, publish_curriculum,
                                         require_live_ai)
from app.services.practice_service import PracticeError, available_case, start_session, visible_cases
from app.services.scenario_engine import apply_event

ROOT = Path(__file__).resolve().parents[1]


class FixtureEmbedder:
    """Exercise the production index contract, deterministic vectors, zero HTTP."""
    remote = True
    provider = 'openai'
    model = 'unit-test-embedding'
    identity = 'unit-test-only:four-cases'

    def __init__(self):
        self.local = Embedder({**DEFAULTS, 'TESTING': True, 'EMBED_PROVIDER': 'test'})

    def embed(self, texts):
        return self.local.embed(texts)


class CurriculumTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password_hash = generate_password_hash('only-a-test-password', method='scrypt')

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.app = create_app('testing', {
            'AUTH_RATE_LIMIT_ENABLED': False, 'WTF_CSRF_ENABLED': False,
            'AI_CHAT_ENABLED': True, 'AI_TUTOR_ENABLED': True,
            'LLM_PROVIDER': 'openai', 'LLM_MODEL': 'unit-test-model',
            'LLM_BASE_URL': 'https://example.invalid/v1', 'LLM_API_KEY': 'unit-test-not-a-key',
            'EMBED_PROVIDER': 'test', 'AI_TOP_K': 6, 'AI_MAX_CONTEXT_CHARS': 4000,
        }, instance_path=self.temp.name)
        self.addCleanup(self.cleanup)
        self.ctx = self.app.app_context(); self.ctx.push()
        upgrade(directory=str(ROOT / 'migrations'))
        for identifier, role in [(1, 'ADMIN'), (2, 'STUDENT'), (3, 'STUDENT')]:
            db.session.add(User(id=identifier, email_normalized=f'u{identifier}@example.com',
                password_hash=self.password_hash, display_name=f'User {identifier}', role=role, is_test_account=0))
        db.session.commit()
        self.packages = curriculum_packages()
        self.embedder = FixtureEmbedder()
        self.admin = 'u1@example.com'

    def cleanup(self):
        db.session.remove(); db.engine.dispose(); self.ctx.pop(); self.temp.cleanup()

    def install_data(self):
        import_packages(self.packages, self.admin)
        ids = [v.id for v in bundle_versions(self.packages)]
        for identifier in ids:
            index_case(identifier, self.embedder)
        return ids

    def publish(self):
        self.install_data()
        return publish_curriculum(self.packages, self.admin, self.embedder)

    def plan(self, package, question, state=None):
        content = package['content']
        docs = case_documents(content)
        vectors = []
        for offset in range(0, len(docs), 32):
            vectors.extend(self.embedder.embed([d['search_text'] for d in docs[offset:offset+32]]))
        snap = {'content': content, 'before': deepcopy(state or content['initial_state']), 'history': [],
                'rows': [{**d, 'vector': v, 'source_hash': digest(docs)} for d, v in zip(docs, vectors)]}
        return plan_patient_turn(snap, question, self.embedder.embed([question]), self.app.config)

    def test_four_distinct_patients_and_complete_weighted_rubrics(self):
        self.assertEqual(sorted(p['content']['patient']['gender'] for p in self.packages), ['Nam','Nam','Nữ','Nữ'])
        self.assertEqual(len({p['content']['patient']['portrait_key'] for p in self.packages}), 4)
        self.assertEqual(len({p['content']['public']['reason'] for p in self.packages}), 4)
        for package in self.packages:
            self.assertGreaterEqual(len(package['content']['facts']), 35)
            self.assertEqual(len(package['rubric']), 9)
            self.assertEqual(sum(r['weight'] for r in package['rubric']), 100)
            self.assertFalse(package['content']['actions'])
            self.assertEqual(package['review']['medical']['status'], 'NOT_REVIEWED')
            self.assertIsNone(package['review']['medical']['reviewer'])
            for criterion in package['rubric']:
                self.assertIn('LEARNER_MESSAGE', criterion['evidence_sources'])

    def test_every_authored_query_retrieves_expected_facts(self):
        for package in self.packages:
            for row in package['content']['development_tests']:
                with self.subTest(case=package['case_code'], question=row['question']):
                    found = {h['source_id'] for h in self.plan(package, row['question'])['hits']}
                    self.assertTrue(set(row['expected_fact_ids']) <= found, (row['expected_fact_ids'], found))

    def test_privacy_filter_and_repair_for_each_patient(self):
        for package in self.packages:
            with self.subTest(case=package['case_code']):
                content = package['content']
                hits = self.plan(package, 'Bạn lo lắng sợ điều gì nhất?')['hits']
                self.assertNotIn('F_CONCERN', {h['source_id'] for h in hits})
                state = apply_event(content, content['initial_state'], 'ASK_CONCERN')['state']
                self.assertEqual(state['state_id'], 'S2')
                state = apply_event(content, state, 'PRIVACY_PERMISSION')['state']
                self.assertEqual(state['state_id'], 'S3')
                self.assertIn('F_CONCERN', {h['source_id'] for h in self.plan(package, 'Bạn lo lắng sợ điều gì nhất?', state)['hits']})
                for path in content['branch_paths']:
                    state = deepcopy(path['initial'])
                    for step in path['steps']:
                        state = apply_event(content, state, step['event'])['state']
                        self.assertEqual(state['state_id'], step['expected_state'])

    def test_absent_and_unknown_are_explicit_not_inferred(self):
        for package in self.packages:
            facts = {f['topic']: f for f in package['content']['facts']}
            self.assertEqual(facts['FEVER']['knowledge'], 'ABSENT')
            self.assertEqual(facts['ALLERGY']['knowledge'], 'UNKNOWN')
            self.assertEqual(facts['TESTS']['knowledge'], 'UNSPECIFIED')
        linh = {f['topic']: f for f in self.packages[1]['content']['facts']}
        self.assertEqual(linh['PREGNANCY']['knowledge'], 'UNKNOWN')
        self.assertEqual(linh['SEXUAL']['disclosure']['min_cooperation'], 2)

    def test_draft_import_never_publishes_itself(self):
        import_packages(self.packages, self.admin)
        self.assertTrue(all(v.status == 'DRAFT' for v in bundle_versions(self.packages)))
        with self.app.test_request_context():
            self.assertEqual(visible_cases(db.session.get(User,2)), [])

    def test_non_demo_without_coursework_scope_is_invalid(self):
        package = deepcopy(self.packages[0]); del package['content']['delivery']
        with self.assertRaises(CaseValidationError): validate_package(package)

    def test_coursework_with_canned_chat_mode_is_invalid(self):
        package = deepcopy(self.packages[0]); del package['content']['dialogue']
        with self.assertRaises(CaseValidationError): validate_package(package)

    def test_demo_or_disabled_ai_cannot_release(self):
        self.app.config['AI_TUTOR_ENABLED'] = False
        with self.assertRaises(AIError): require_live_ai()
        self.app.config.update(AI_TUTOR_ENABLED=True, LLM_PROVIDER='demo')
        with self.assertRaises(AIError): require_live_ai()

    def test_atomic_release_fails_if_one_index_is_missing(self):
        import_packages(self.packages, self.admin)
        versions = bundle_versions(self.packages)
        for v in versions[:3]: index_case(v.id, self.embedder)
        with self.assertRaises(AIError): publish_curriculum(self.packages, self.admin, self.embedder)
        self.assertTrue(all(v.status == 'DRAFT' for v in bundle_versions(self.packages)))
        self.assertEqual(db.session.scalar(db.select(db.func.count()).select_from(AuditLog).where(AuditLog.action=='COURSEWORK_PUBLISHED')),0)

    def test_only_admin_can_release(self):
        self.install_data()
        with self.assertRaises(CaseValidationError):
            publish_curriculum(self.packages, 'u2@example.com', self.embedder)
        self.assertTrue(all(v.status == 'DRAFT' for v in bundle_versions(self.packages)))

    def test_release_preserves_old_session_and_messages(self):
        old_package = load_package(ROOT/'data/case_updates/mq_com_01_v3.json')
        import_packages([old_package], self.admin)
        old = db.session.scalar(db.select(CaseVersion)); old_id = old.id
        session_id,_ = start_session(1,1,old_id,uuid4().hex,'TEST')
        old_hash = old.content_hash
        opening = db.session.scalar(db.select(Message.content_text).where(Message.session_id==session_id))
        self.publish()
        self.assertEqual(db.session.get(CaseVersion,old_id).status,'ARCHIVED')
        self.assertEqual(db.session.get(CaseVersion,old_id).content_hash,old_hash)
        self.assertEqual(db.session.get(SimulationSession,session_id).case_version_id,old_id)
        self.assertEqual(db.session.scalar(db.select(Message.content_text).where(Message.session_id==session_id)),opening)
        with self.app.test_request_context():
            for user_id in [1,2]: self.assertEqual(len(visible_cases(db.session.get(User,user_id))),4)
        with self.assertRaises(PracticeError): available_case(old_id,db.session.get(User,1))
        from flask_login import login_user
        from app.security import get_owned_session
        with self.app.test_request_context():
            login_user(db.session.get(User,1))
            self.assertEqual(get_owned_session(session_id).case_version_id,old_id)

    def test_published_catalog_does_not_expose_private_payload(self):
        self.publish()
        client = self.app.test_client()
        client.post('/auth/login',data={'email':'u2@example.com','password':'only-a-test-password'})
        response=client.get('/cases');html=response.get_data(as_text=True)
        self.assertEqual(response.status_code,200)
        for name in ['Nguyễn Văn An','Trần Ngọc Linh','Lê Quốc Minh','Phạm Thu Hương']:self.assertIn(name,html)
        for text in ['Không thấy phân đen','ba ngày trước','levels_json','F_CONCERN']:self.assertNotIn(text,html)
        self.assertEqual(html.count('class="mq-panel case-card h-100"'),4)
        for v in bundle_versions(self.packages):
            detail=client.get(f'/cases/{v.id}').get_data(as_text=True)
            self.assertIn('Bắt đầu thực hành',detail)
            self.assertNotIn('Bắt đầu lượt kiểm thử',detail)

    def test_start_checks_real_configuration_and_index_before_consuming_quota(self):
        rows=self.publish()
        with self.assertRaises(PracticeError): start_session(2,1,rows[0][0],uuid4().hex,'PRACTICE')
        self.assertEqual(db.session.scalar(db.select(db.func.count()).select_from(SimulationSession)),0)
        with patch('app.services.catalog_service.Embedder',return_value=self.embedder):
            sid,created=start_session(2,1,rows[0][0],uuid4().hex,'PRACTICE')
        self.assertTrue(created);self.assertEqual(db.session.get(SimulationSession,sid).mode,'PRACTICE')

    def test_second_publication_is_idempotent_and_does_not_fabricate_review(self):
        self.publish()
        before=db.session.scalar(db.select(db.func.count()).select_from(AuditLog))
        publish_curriculum(self.packages,self.admin,self.embedder)
        self.assertEqual(db.session.scalar(db.select(db.func.count()).select_from(AuditLog)),before)
        for v in bundle_versions(self.packages):
            self.assertFalse(v.review_json['release']['clinical_approval'])
            self.assertEqual(v.review_json['medical']['status'],'NOT_REVIEWED')

    def test_conflicting_content_and_newer_versions_are_not_overwritten(self):
        import_packages(self.packages,self.admin)
        v=bundle_versions(self.packages)[0];v.title='Custom edit';db.session.commit()
        with self.assertRaises(CaseValidationError):bundle_versions(self.packages)
        db.session.rollback()
        v=db.session.get(CaseVersion,v.id);v.title=self.packages[0]['title'];db.session.commit()
        newer=deepcopy(self.packages[0]);newer['version_no']+=1
        import_packages([newer],self.admin)
        with self.assertRaises(CaseValidationError):bundle_versions(self.packages)

    def test_cli_backup_install_and_repeat_without_reembedding(self):
        runner=self.app.test_cli_runner()
        with patch('app.services.catalog_service.Embedder',return_value=self.embedder):
            result=runner.invoke(args=['catalog','install','--admin-email',self.admin])
            self.assertEqual(result.exit_code,0,result.output)
            self.assertIn('SẴN SÀNG: MQ_COM_04',result.output)
            backup=list(Path(self.temp.name).glob('backups/before_four_cases_*.sqlite'))
            self.assertEqual(len(backup),1)
            with closing(sqlite3.connect(backup[0])) as con:
                self.assertEqual(con.execute('select count(*) from users').fetchone()[0],3)
                self.assertEqual(con.execute('select count(*) from case_versions').fetchone()[0],0)
            with patch('app.catalog.index_case',side_effect=AssertionError('must reuse valid index')):
                result=runner.invoke(args=['catalog','install','--admin-email',self.admin])
                self.assertEqual(result.exit_code,0,result.output)
        self.assertEqual(len(bundle_versions(self.packages)),4)

    def test_failed_embedding_cli_leaves_drafts_and_is_resumable(self):
        runner=self.app.test_cli_runner()
        with patch('app.services.catalog_service.Embedder',return_value=self.embedder):
            with patch('app.catalog.index_case',side_effect=AIError('fixture network failure')):
                result=runner.invoke(args=['catalog','install','--admin-email',self.admin])
                self.assertNotEqual(result.exit_code,0)
            self.assertTrue(all(v.status=='DRAFT' for v in bundle_versions(self.packages)))
            result=runner.invoke(args=['catalog','install','--admin-email',self.admin])
            self.assertEqual(result.exit_code,0,result.output)
        self.assertTrue(all(v.status=='PUBLISHED' for v in bundle_versions(self.packages)))

    def test_new_draft_does_not_hide_published_case(self):
        self.publish()
        newer=deepcopy(self.packages[0]);newer['version_no']+=1;newer['title']='Future unpublished content'
        import_packages([newer],self.admin)
        with self.app.test_request_context():
            for user_id in [1,2]:
                items=visible_cases(db.session.get(User,user_id))
                self.assertEqual(len(items),4)
                self.assertEqual(items[0]['case']['version_no'],4)


if __name__=='__main__':unittest.main()
