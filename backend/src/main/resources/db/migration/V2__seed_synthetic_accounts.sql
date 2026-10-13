-- ============================================================================
-- Synthetic course accounts (FR-AUTH-01) and the four contract roles.
--
-- Every account here is SYNTHETIC demo data. Only BCrypt hashes are stored;
-- the demo password itself is documented in backend/README.md and is repeated in
-- SchemaMigrationTest so a broken hash fails the build. No real credential is
-- committed anywhere.
--
-- The five hashes are distinct on purpose: reusing one hash across accounts would
-- reveal that all demo accounts share a password. All hashes use BCrypt strength
-- 10 ($2a$10$...), which is the Spring Security default.
--
-- research_doctor holds two roles so the multi-role rules (CurrentUser.roles is a
-- union, menus are the union of both role menus) have a real account to test.
-- ============================================================================

INSERT INTO sys_role (role_code) VALUES ('ADMIN');
INSERT INTO sys_role (role_code) VALUES ('RESEARCHER');
INSERT INTO sys_role (role_code) VALUES ('DOCTOR');
INSERT INTO sys_role (role_code) VALUES ('PATIENT');

INSERT INTO sys_user (username, password_hash, status, created_at) VALUES
  ('admin',           '$2a$10$5GN1/tJxl9udBYhmwgsLB./YUj.5oid6bMYJp4WYtQ6JDF1QkvgbO', 'ACTIVE', CURRENT_TIMESTAMP),
  ('researcher',      '$2a$10$MKSbtJhVOVPlQStvkWxkZOjsx.r65rsxB08VmIiMg.KfTsOxCLNta', 'ACTIVE', CURRENT_TIMESTAMP),
  ('doctor',          '$2a$10$d3kTRhFBHpafdYORfE6OAOE1Q5pJimUhLoJmoIlBXjYqs3PQ.rZJK', 'ACTIVE', CURRENT_TIMESTAMP),
  ('patient',         '$2a$10$XtOyxJCuWI1S9XBl9q/hM.1cGt/6K742H/pV9NrhbDt10zadmjzD2', 'ACTIVE', CURRENT_TIMESTAMP),
  ('research_doctor', '$2a$10$jtuczSE3ol7d5OER42setOM6w3YaOcYWjLi6F3h093xtBjfxyJCXy', 'ACTIVE', CURRENT_TIMESTAMP);

-- One account per contract role.
INSERT INTO user_role (user_id, role_id)
SELECT u.id, r.id FROM sys_user u JOIN sys_role r ON r.role_code = 'ADMIN'      WHERE u.username = 'admin';
INSERT INTO user_role (user_id, role_id)
SELECT u.id, r.id FROM sys_user u JOIN sys_role r ON r.role_code = 'RESEARCHER' WHERE u.username = 'researcher';
INSERT INTO user_role (user_id, role_id)
SELECT u.id, r.id FROM sys_user u JOIN sys_role r ON r.role_code = 'DOCTOR'     WHERE u.username = 'doctor';
INSERT INTO user_role (user_id, role_id)
SELECT u.id, r.id FROM sys_user u JOIN sys_role r ON r.role_code = 'PATIENT'    WHERE u.username = 'patient';

-- The multi-role account.
INSERT INTO user_role (user_id, role_id)
SELECT u.id, r.id FROM sys_user u JOIN sys_role r ON r.role_code = 'RESEARCHER' WHERE u.username = 'research_doctor';
INSERT INTO user_role (user_id, role_id)
SELECT u.id, r.id FROM sys_user u JOIN sys_role r ON r.role_code = 'DOCTOR'     WHERE u.username = 'research_doctor';

-- No subject and no subject_permission rows are seeded: demo subjects arrive
-- through the CSV import PR, and grants have no admin API yet.
