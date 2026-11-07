"""Initial P0 schema

Revision ID: 0001_p0
Revises: 
Create Date: 2026-10-26 12:05:17.364235

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0001_p0'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Schema generated from P0 metadata, reviewed before delivery.
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email_normalized', sa.String(length=254), nullable=False),
    sa.Column('password_hash', sa.Text(), nullable=False),
    sa.Column('display_name', sa.String(length=100), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('is_test_account', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.String(length=32), nullable=False),
    sa.CheckConstraint("role IN ('STUDENT','ADMIN')", name=op.f('ck_users_role')),
    sa.CheckConstraint("status IN ('ACTIVE','LOCKED')", name=op.f('ck_users_status')),
    sa.CheckConstraint('is_test_account IN (0,1)', name=op.f('ck_users_test_flag')),
    sa.CheckConstraint('length(trim(email_normalized)) > 0', name=op.f('ck_users_email_not_blank')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('email_normalized', name=op.f('uq_users_email_normalized'))
    )
    op.create_table('audit_log',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('actor_user_id', sa.Integer(), nullable=True),
    sa.Column('entity_type', sa.String(length=40), nullable=False),
    sa.Column('entity_id', sa.String(length=64), nullable=False),
    sa.Column('action', sa.String(length=60), nullable=False),
    sa.Column('occurred_at', sa.String(length=32), nullable=False),
    sa.Column('metadata_json', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], name=op.f('fk_audit_log_actor_user_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_log'))
    )
    op.create_table('cases',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_code', sa.String(length=40), nullable=False),
    sa.Column('created_by_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.String(length=32), nullable=False),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name=op.f('fk_cases_created_by_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_cases')),
    sa.UniqueConstraint('case_code', name=op.f('uq_cases_case_code'))
    )
    op.create_table('case_versions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.Integer(), nullable=False),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.Column('created_by_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('content_json', sa.JSON(), nullable=False),
    sa.Column('review_json', sa.JSON(), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('demo_only', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.String(length=32), nullable=False),
    sa.CheckConstraint("status != 'PUBLISHED' OR demo_only = 0", name=op.f('ck_case_versions_no_demo_publish')),
    sa.CheckConstraint("status IN ('DRAFT','PENDING_REVIEW','APPROVED','PUBLISHED','ARCHIVED')", name=op.f('ck_case_versions_status')),
    sa.CheckConstraint('demo_only IN (0,1)', name=op.f('ck_case_versions_demo_flag')),
    sa.CheckConstraint('version_no > 0', name=op.f('ck_case_versions_version_positive')),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], name=op.f('fk_case_versions_case_id_cases'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name=op.f('fk_case_versions_created_by_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_case_versions')),
    sa.UniqueConstraint('case_id', 'version_no', name=op.f('uq_case_versions_case_id_version_no'))
    )
    with op.batch_alter_table('case_versions', schema=None) as batch_op:
        batch_op.create_index('uq_case_versions_one_published', ['case_id'], unique=True, sqlite_where=sa.text("status = 'PUBLISHED'"))

    op.create_table('rubric_criteria',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_version_id', sa.Integer(), nullable=False),
    sa.Column('criterion_code', sa.String(length=40), nullable=False),
    sa.Column('group_code', sa.String(length=24), nullable=False),
    sa.Column('weight', sa.Integer(), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('levels_json', sa.JSON(), nullable=False),
    sa.Column('sort_no', sa.Integer(), nullable=False),
    sa.CheckConstraint("group_code IN ('CURRENT','RELATED','COMMUNICATION','REASONING','SUMMARY')", name=op.f('ck_rubric_criteria_group_code')),
    sa.CheckConstraint('sort_no > 0', name=op.f('ck_rubric_criteria_sort_positive')),
    sa.CheckConstraint('weight > 0 AND weight <= 100', name=op.f('ck_rubric_criteria_weight')),
    sa.ForeignKeyConstraint(['case_version_id'], ['case_versions.id'], name=op.f('fk_rubric_criteria_case_version_id_case_versions'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rubric_criteria')),
    sa.UniqueConstraint('case_version_id', 'criterion_code', name=op.f('uq_rubric_criteria_case_version_id_criterion_code')),
    sa.UniqueConstraint('id', 'case_version_id', name=op.f('uq_rubric_criteria_id_case_version_id'))
    )
    op.create_table('sessions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('case_version_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('mode', sa.String(length=16), nullable=False),
    sa.Column('state_json', sa.JSON(), nullable=False),
    sa.Column('state_version', sa.Integer(), nullable=False),
    sa.Column('turn_index', sa.Integer(), nullable=False),
    sa.Column('assisted', sa.Integer(), nullable=False),
    sa.Column('start_request_key', sa.String(length=100), nullable=False),
    sa.Column('start_input_hash', sa.String(length=64), nullable=False),
    sa.Column('started_at', sa.String(length=32), nullable=False),
    sa.Column('ended_at', sa.String(length=32), nullable=True),
    sa.CheckConstraint("(status = 'ACTIVE' AND ended_at IS NULL) OR (status != 'ACTIVE' AND ended_at IS NOT NULL)", name=op.f('ck_sessions_end_time')),
    sa.CheckConstraint("mode IN ('PRACTICE','TEST')", name=op.f('ck_sessions_mode')),
    sa.CheckConstraint("status IN ('ACTIVE','COMPLETED','ABANDONED')", name=op.f('ck_sessions_status')),
    sa.CheckConstraint('assisted IN (0,1)', name=op.f('ck_sessions_assisted')),
    sa.CheckConstraint('state_version >= 0 AND turn_index BETWEEN 0 AND 20', name=op.f('ck_sessions_counters')),
    sa.ForeignKeyConstraint(['case_version_id'], ['case_versions.id'], name=op.f('fk_sessions_case_version_id_case_versions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_sessions_user_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sessions')),
    sa.UniqueConstraint('id', 'case_version_id', name=op.f('uq_sessions_id_case_version_id')),
    sa.UniqueConstraint('id', 'user_id', name=op.f('uq_sessions_id_user_id')),
    sa.UniqueConstraint('user_id', 'start_request_key', name=op.f('uq_sessions_user_id_start_request_key'))
    )
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.create_index('ix_sessions_user_started', ['user_id', 'started_at'], unique=False)

    op.create_table('session_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('session_id', sa.Integer(), nullable=False),
    sa.Column('request_key', sa.String(length=100), nullable=False),
    sa.Column('event_code', sa.String(length=60), nullable=False),
    sa.Column('event_type', sa.String(length=24), nullable=False),
    sa.Column('before_state', sa.JSON(), nullable=False),
    sa.Column('after_state', sa.JSON(), nullable=False),
    sa.Column('evidence_payload_json', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.String(length=32), nullable=False),
    sa.CheckConstraint("event_type IN ('TURN','ACTION','HINT_USED','SESSION_CLOSED')", name=op.f('ck_session_events_event_type')),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_session_events_session_id_sessions'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_session_events')),
    sa.UniqueConstraint('id', 'session_id', name=op.f('uq_session_events_id_session_id')),
    sa.UniqueConstraint('session_id', 'request_key', 'event_code', name=op.f('uq_session_events_session_id_request_key_event_code'))
    )
    with op.batch_alter_table('session_events', schema=None) as batch_op:
        batch_op.create_index('ix_session_events_session_created', ['session_id', 'created_at'], unique=False)

    op.create_table('submissions',
    sa.Column('session_id', sa.Integer(), nullable=False),
    sa.Column('summary_json', sa.JSON(), nullable=False),
    sa.Column('submitted_at', sa.String(length=32), nullable=False),
    sa.Column('payload_hash', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_submissions_session_id_sessions'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('session_id', name=op.f('pk_submissions'))
    )
    op.create_table('evaluations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('session_id', sa.Integer(), nullable=False),
    sa.Column('case_version_id', sa.Integer(), nullable=False),
    sa.Column('evaluation_no', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('total_points_x2', sa.Integer(), nullable=True),
    sa.Column('input_hash', sa.String(length=64), nullable=False),
    sa.Column('config_json', sa.JSON(), nullable=False),
    sa.Column('feedback_json', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.String(length=32), nullable=False),
    sa.CheckConstraint("(status = 'VALID' AND total_points_x2 IS NOT NULL AND total_points_x2 BETWEEN 0 AND 200) OR (status != 'VALID' AND total_points_x2 IS NULL)", name=op.f('ck_evaluations_valid_total_only')),
    sa.CheckConstraint("status IN ('PENDING','PROCESSING','VALID','NEEDS_REVIEW','ERROR')", name=op.f('ck_evaluations_status')),
    sa.CheckConstraint('evaluation_no > 0', name=op.f('ck_evaluations_number_positive')),
    sa.ForeignKeyConstraint(['session_id', 'case_version_id'], ['sessions.id', 'sessions.case_version_id'], name=op.f('fk_evaluations_session_id_sessions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['session_id'], ['submissions.session_id'], name=op.f('fk_evaluations_session_id_submissions'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_evaluations')),
    sa.UniqueConstraint('id', 'session_id', 'case_version_id', name=op.f('uq_evaluations_id_session_id_case_version_id')),
    sa.UniqueConstraint('id', 'session_id', name=op.f('uq_evaluations_id_session_id')),
    sa.UniqueConstraint('session_id', 'evaluation_no', name=op.f('uq_evaluations_session_id_evaluation_no'))
    )
    with op.batch_alter_table('evaluations', schema=None) as batch_op:
        batch_op.create_index('ix_evaluations_session_status_number', ['session_id', 'status', 'evaluation_no'], unique=False)

    op.create_table('ai_operations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('session_id', sa.Integer(), nullable=False),
    sa.Column('evaluation_id', sa.Integer(), nullable=True),
    sa.Column('request_key', sa.String(length=100), nullable=False),
    sa.Column('input_hash', sa.String(length=64), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('expected_state_version', sa.Integer(), nullable=False),
    sa.Column('input_payload_json', sa.JSON(), nullable=False),
    sa.Column('started_at', sa.String(length=32), nullable=False),
    sa.Column('finished_at', sa.String(length=32), nullable=True),
    sa.CheckConstraint("(kind = 'ASSESSMENT' AND evaluation_id IS NOT NULL) OR (kind != 'ASSESSMENT' AND evaluation_id IS NULL)", name=op.f('ck_ai_operations_assessment_target')),
    sa.CheckConstraint("kind IN ('TURN','ACTION','ASSESSMENT')", name=op.f('ck_ai_operations_kind')),
    sa.CheckConstraint("status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','CONFLICT')", name=op.f('ck_ai_operations_status')),
    sa.CheckConstraint('expected_state_version >= 0', name=op.f('ck_ai_operations_state_version')),
    sa.ForeignKeyConstraint(['evaluation_id', 'session_id'], ['evaluations.id', 'evaluations.session_id'], name=op.f('fk_ai_operations_evaluation_id_evaluations'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_ai_operations_session_id_sessions'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_operations')),
    sa.UniqueConstraint('evaluation_id', name=op.f('uq_ai_operations_evaluation_id')),
    sa.UniqueConstraint('id', 'session_id', name=op.f('uq_ai_operations_id_session_id')),
    sa.UniqueConstraint('session_id', 'request_key', name=op.f('uq_ai_operations_session_id_request_key'))
    )
    with op.batch_alter_table('ai_operations', schema=None) as batch_op:
        batch_op.create_index('uq_ai_operations_one_running', ['status'], unique=True, sqlite_where=sa.text("status = 'RUNNING'"))

    op.create_table('evaluation_items',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('evaluation_id', sa.Integer(), nullable=False),
    sa.Column('criterion_id', sa.Integer(), nullable=False),
    sa.Column('session_id', sa.Integer(), nullable=False),
    sa.Column('case_version_id', sa.Integer(), nullable=False),
    sa.Column('level', sa.String(length=20), nullable=False),
    sa.Column('points_x2', sa.Integer(), nullable=True),
    sa.Column('reason_text', sa.Text(), nullable=False),
    sa.CheckConstraint("(level = 'UNDETERMINED' AND points_x2 IS NULL) OR (level != 'UNDETERMINED' AND points_x2 IS NOT NULL AND points_x2 BETWEEN 0 AND 200)", name=op.f('ck_evaluation_items_points')),
    sa.CheckConstraint("level != 'MISSED' OR points_x2 = 0", name=op.f('ck_evaluation_items_missed_zero')),
    sa.CheckConstraint("level IN ('ACHIEVED','PARTIAL','MISSED','UNDETERMINED')", name=op.f('ck_evaluation_items_level')),
    sa.ForeignKeyConstraint(['criterion_id', 'case_version_id'], ['rubric_criteria.id', 'rubric_criteria.case_version_id'], name=op.f('fk_evaluation_items_criterion_id_rubric_criteria'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['evaluation_id', 'session_id', 'case_version_id'], ['evaluations.id', 'evaluations.session_id', 'evaluations.case_version_id'], name=op.f('fk_evaluation_items_evaluation_id_evaluations'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_evaluation_items')),
    sa.UniqueConstraint('evaluation_id', 'criterion_id', name=op.f('uq_evaluation_items_evaluation_id_criterion_id')),
    sa.UniqueConstraint('id', 'session_id', name=op.f('uq_evaluation_items_id_session_id'))
    )
    op.create_table('ai_calls',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('operation_id', sa.Integer(), nullable=False),
    sa.Column('stage', sa.String(length=16), nullable=False),
    sa.Column('attempt_no', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('requested_at', sa.String(length=32), nullable=False),
    sa.Column('reserved_cost_microusd', sa.Integer(), nullable=False),
    sa.Column('actual_cost_microusd', sa.Integer(), nullable=True),
    sa.Column('usage_json', sa.JSON(), nullable=False),
    sa.Column('configuration_json', sa.JSON(), nullable=False),
    sa.Column('error_code', sa.String(length=80), nullable=True),
    sa.Column('response_hash', sa.String(length=64), nullable=True),
    sa.CheckConstraint("stage IN ('INTENT','PATIENT','TUTOR','TOKEN_COUNT')", name=op.f('ck_ai_calls_stage')),
    sa.CheckConstraint("status IN ('RESERVED','SENT','SUCCEEDED','FAILED','UNKNOWN','CANCELLED')", name=op.f('ck_ai_calls_status')),
    sa.CheckConstraint('attempt_no > 0', name=op.f('ck_ai_calls_attempt_positive')),
    sa.CheckConstraint('reserved_cost_microusd >= 0 AND (actual_cost_microusd IS NULL OR actual_cost_microusd >= 0)', name=op.f('ck_ai_calls_costs_nonnegative')),
    sa.ForeignKeyConstraint(['operation_id'], ['ai_operations.id'], name=op.f('fk_ai_calls_operation_id_ai_operations'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_calls')),
    sa.UniqueConstraint('operation_id', 'stage', 'attempt_no', name=op.f('uq_ai_calls_operation_id_stage_attempt_no'))
    )
    with op.batch_alter_table('ai_calls', schema=None) as batch_op:
        batch_op.create_index('ix_ai_calls_requested_status', ['requested_at', 'status'], unique=False)

    op.create_table('messages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('session_id', sa.Integer(), nullable=False),
    sa.Column('operation_id', sa.Integer(), nullable=True),
    sa.Column('seq_no', sa.Integer(), nullable=False),
    sa.Column('sender', sa.String(length=16), nullable=False),
    sa.Column('content_text', sa.Text(), nullable=False),
    sa.Column('created_at', sa.String(length=32), nullable=False),
    sa.CheckConstraint("operation_id IS NOT NULL OR sender = 'PATIENT'", name=op.f('ck_messages_opening_patient')),
    sa.CheckConstraint("sender IN ('LEARNER','PATIENT')", name=op.f('ck_messages_sender')),
    sa.CheckConstraint('seq_no > 0', name=op.f('ck_messages_sequence_positive')),
    sa.ForeignKeyConstraint(['operation_id', 'session_id'], ['ai_operations.id', 'ai_operations.session_id'], name=op.f('fk_messages_operation_id_ai_operations'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_messages_session_id_sessions'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_messages')),
    sa.UniqueConstraint('id', 'session_id', name=op.f('uq_messages_id_session_id')),
    sa.UniqueConstraint('operation_id', 'sender', name=op.f('uq_messages_operation_id_sender')),
    sa.UniqueConstraint('session_id', 'seq_no', name=op.f('uq_messages_session_id_seq_no'))
    )
    op.create_table('evidence',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('item_id', sa.Integer(), nullable=False),
    sa.Column('session_id', sa.Integer(), nullable=False),
    sa.Column('message_id', sa.Integer(), nullable=True),
    sa.Column('event_id', sa.Integer(), nullable=True),
    sa.Column('submission_session_id', sa.Integer(), nullable=True),
    sa.Column('field_path', sa.String(length=100), nullable=True),
    sa.Column('quote_text', sa.Text(), nullable=False),
    sa.Column('start_offset', sa.Integer(), nullable=True),
    sa.Column('end_offset', sa.Integer(), nullable=True),
    sa.CheckConstraint('(message_id IS NOT NULL) + (event_id IS NOT NULL) + (submission_session_id IS NOT NULL) = 1', name=op.f('ck_evidence_exactly_one_source')),
    sa.CheckConstraint('(start_offset IS NULL AND end_offset IS NULL) OR (start_offset IS NOT NULL AND end_offset IS NOT NULL AND start_offset >= 0 AND end_offset > start_offset)', name=op.f('ck_evidence_offset_range')),
    sa.CheckConstraint('submission_session_id IS NULL OR submission_session_id = session_id', name=op.f('ck_evidence_submission_same_session')),
    sa.ForeignKeyConstraint(['event_id', 'session_id'], ['session_events.id', 'session_events.session_id'], name=op.f('fk_evidence_event_id_session_events'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['item_id', 'session_id'], ['evaluation_items.id', 'evaluation_items.session_id'], name=op.f('fk_evidence_item_id_evaluation_items'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['message_id', 'session_id'], ['messages.id', 'messages.session_id'], name=op.f('fk_evidence_message_id_messages'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['submission_session_id'], ['submissions.session_id'], name=op.f('fk_evidence_submission_session_id_submissions'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_evidence'))
    )

    # SQLite guards: invariant history and rubric-based item scores.
    op.execute("""CREATE TRIGGER trg_submission_completed BEFORE INSERT ON submissions WHEN (SELECT status FROM sessions WHERE id=NEW.session_id) != 'COMPLETED' BEGIN SELECT RAISE(ABORT, 'submission requires completed session'); END""")
    op.execute("""CREATE TRIGGER trg_submission_no_update BEFORE UPDATE ON submissions BEGIN SELECT RAISE(ABORT, 'submission is immutable'); END""")
    op.execute("""CREATE TRIGGER trg_submission_no_delete BEFORE DELETE ON submissions BEGIN SELECT RAISE(ABORT, 'submission is immutable'); END""")
    op.execute("""CREATE TRIGGER trg_session_identity BEFORE UPDATE OF user_id, case_version_id, start_request_key, start_input_hash ON sessions WHEN OLD.user_id != NEW.user_id OR OLD.case_version_id != NEW.case_version_id OR OLD.start_request_key != NEW.start_request_key OR OLD.start_input_hash != NEW.start_input_hash BEGIN SELECT RAISE(ABORT, 'session identity is immutable'); END""")
    op.execute("""CREATE TRIGGER trg_session_closed BEFORE UPDATE ON sessions WHEN OLD.status != 'ACTIVE' BEGIN SELECT RAISE(ABORT, 'closed session is immutable'); END""")
    op.execute("""CREATE TRIGGER trg_case_locked_content BEFORE UPDATE OF title, content_json, content_hash, case_id, version_no, demo_only, created_by_id, created_at ON case_versions WHEN OLD.status IN ('APPROVED','PUBLISHED','ARCHIVED') BEGIN SELECT RAISE(ABORT, 'approved case content is immutable'); END""")
    op.execute("""CREATE TRIGGER trg_case_no_reopen_draft BEFORE UPDATE OF status ON case_versions WHEN OLD.status IN ('APPROVED','PUBLISHED','ARCHIVED') AND NEW.status IN ('DRAFT','PENDING_REVIEW') BEGIN SELECT RAISE(ABORT, 'create a new case version'); END""")
    op.execute("""CREATE TRIGGER trg_rubric_locked_insert BEFORE INSERT ON rubric_criteria WHEN (SELECT status FROM case_versions WHERE id=NEW.case_version_id) IN ('APPROVED','PUBLISHED','ARCHIVED') BEGIN SELECT RAISE(ABORT, 'approved rubric is immutable'); END""")
    op.execute("""CREATE TRIGGER trg_rubric_locked_update BEFORE UPDATE ON rubric_criteria WHEN (SELECT status FROM case_versions WHERE id=OLD.case_version_id) IN ('APPROVED','PUBLISHED','ARCHIVED') OR (SELECT status FROM case_versions WHERE id=NEW.case_version_id) IN ('APPROVED','PUBLISHED','ARCHIVED') BEGIN SELECT RAISE(ABORT, 'approved rubric is immutable'); END""")
    op.execute("""CREATE TRIGGER trg_rubric_locked_delete BEFORE DELETE ON rubric_criteria WHEN (SELECT status FROM case_versions WHERE id=OLD.case_version_id) IN ('APPROVED','PUBLISHED','ARCHIVED') BEGIN SELECT RAISE(ABORT, 'approved rubric is immutable'); END""")
    op.execute("""CREATE TRIGGER trg_item_score_insert BEFORE INSERT ON evaluation_items WHEN (NEW.level='ACHIEVED' AND NEW.points_x2 != 2 * (SELECT weight FROM rubric_criteria WHERE id=NEW.criterion_id)) OR (NEW.level='PARTIAL' AND NEW.points_x2 != (SELECT weight FROM rubric_criteria WHERE id=NEW.criterion_id)) BEGIN SELECT RAISE(ABORT, 'item score must follow rubric weight'); END""")
    op.execute("""CREATE TRIGGER trg_item_score_update BEFORE UPDATE ON evaluation_items WHEN (NEW.level='ACHIEVED' AND NEW.points_x2 != 2 * (SELECT weight FROM rubric_criteria WHERE id=NEW.criterion_id)) OR (NEW.level='PARTIAL' AND NEW.points_x2 != (SELECT weight FROM rubric_criteria WHERE id=NEW.criterion_id)) BEGIN SELECT RAISE(ABORT, 'item score must follow rubric weight'); END""")
    # End schema upgrade.


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS trg_submission_completed")
    op.execute("DROP TRIGGER IF EXISTS trg_submission_no_update")
    op.execute("DROP TRIGGER IF EXISTS trg_submission_no_delete")
    op.execute("DROP TRIGGER IF EXISTS trg_session_identity")
    op.execute("DROP TRIGGER IF EXISTS trg_session_closed")
    op.execute("DROP TRIGGER IF EXISTS trg_case_locked_content")
    op.execute("DROP TRIGGER IF EXISTS trg_case_no_reopen_draft")
    op.execute("DROP TRIGGER IF EXISTS trg_rubric_locked_insert")
    op.execute("DROP TRIGGER IF EXISTS trg_rubric_locked_update")
    op.execute("DROP TRIGGER IF EXISTS trg_rubric_locked_delete")
    op.execute("DROP TRIGGER IF EXISTS trg_item_score_insert")
    op.execute("DROP TRIGGER IF EXISTS trg_item_score_update")
    # Schema generated from P0 metadata, reviewed before delivery.
    op.drop_table('evidence')
    op.drop_table('messages')
    with op.batch_alter_table('ai_calls', schema=None) as batch_op:
        batch_op.drop_index('ix_ai_calls_requested_status')

    op.drop_table('ai_calls')
    op.drop_table('evaluation_items')
    with op.batch_alter_table('ai_operations', schema=None) as batch_op:
        batch_op.drop_index('uq_ai_operations_one_running', sqlite_where=sa.text("status = 'RUNNING'"))

    op.drop_table('ai_operations')
    with op.batch_alter_table('evaluations', schema=None) as batch_op:
        batch_op.drop_index('ix_evaluations_session_status_number')

    op.drop_table('evaluations')
    op.drop_table('submissions')
    with op.batch_alter_table('session_events', schema=None) as batch_op:
        batch_op.drop_index('ix_session_events_session_created')

    op.drop_table('session_events')
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.drop_index('ix_sessions_user_started')

    op.drop_table('sessions')
    op.drop_table('rubric_criteria')
    with op.batch_alter_table('case_versions', schema=None) as batch_op:
        batch_op.drop_index('uq_case_versions_one_published', sqlite_where=sa.text("status = 'PUBLISHED'"))

    op.drop_table('case_versions')
    op.drop_table('cases')
    op.drop_table('audit_log')
    op.drop_table('users')
    # ### end Alembic commands ###
