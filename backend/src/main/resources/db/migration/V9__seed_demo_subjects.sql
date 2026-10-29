-- ---------------------------------------------------------------------------
-- Seed demo subjects + grants so GET /api/subjects returns data on a fresh
-- file-based H2 database without waiting for a CSV import.
--
-- PORTABILITY: body is MySQL-8 / H2(MODE=MySQL) compatible (no ENGINE,
-- CHARSET, COMMENT, UNSIGNED, ON UPDATE CURRENT_TIMESTAMP, JSON).
--
-- data_version must match the 'demo-%' CHECK; status must be ACTIVE.
-- ---------------------------------------------------------------------------

INSERT INTO subject (subject_code, alias, status, data_version, created_at) VALUES
  ('DEMO-001', '演示受试者 张三', 'ACTIVE', 'demo-v9-seed', CURRENT_TIMESTAMP),
  ('DEMO-002', '演示受试者 李四', 'ACTIVE', 'demo-v9-seed', CURRENT_TIMESTAMP),
  ('DEMO-003', '演示受试者 王五', 'ACTIVE', 'demo-v9-seed', CURRENT_TIMESTAMP),
  ('DEMO-004', '演示受试者 赵六', 'ACTIVE', 'demo-v9-seed', CURRENT_TIMESTAMP);

-- Grant VIEW permission to every DOCTOR / RESEARCHER / ADMIN so lists are non-empty.
INSERT INTO subject_permission (subject_id, user_id, permission_type)
SELECT s.id, u.id, 'VIEW'
FROM subject s
JOIN sys_user u ON u.username IN ('doctor', 'researcher', 'admin', 'research_doctor')
WHERE s.subject_code IN ('DEMO-001', 'DEMO-002', 'DEMO-003', 'DEMO-004');