-- ClassPing development seed data (PostgreSQL).
-- Run after migrations: psql "$DATABASE_URL" -f apps/core/seeds/seed_data.sql
-- The script is safe to run repeatedly and mirrors apps/core/seeds/*.py.

BEGIN;

-- Locations are hierarchical MPTT rows.  The fixed values form one five-level tree.
DO $$
DECLARE country_id bigint; province_id bigint; city_id bigint;
        district_id bigint; village_id bigint;
BEGIN
    SELECT id INTO country_id FROM locations WHERE code = 'ID' LIMIT 1;
    IF country_id IS NULL THEN
        INSERT INTO locations (name, code, type, parent_id, lft, rght, tree_id, level)
        VALUES ('Indonesia', 'ID', 'COUNTRY', NULL, 1, 10, 1, 0) RETURNING id INTO country_id;
    END IF;
    SELECT id INTO province_id FROM locations WHERE code = '32' LIMIT 1;
    IF province_id IS NULL THEN
        INSERT INTO locations (name, code, type, parent_id, lft, rght, tree_id, level)
        VALUES ('Jawa Barat', '32', 'PROVINCE', country_id, 2, 9, 1, 1) RETURNING id INTO province_id;
    END IF;
    SELECT id INTO city_id FROM locations WHERE code = '3273' LIMIT 1;
    IF city_id IS NULL THEN
        INSERT INTO locations (name, code, type, parent_id, lft, rght, tree_id, level)
        VALUES ('Kota Bandung', '3273', 'CITY', province_id, 3, 8, 1, 2) RETURNING id INTO city_id;
    END IF;
    SELECT id INTO district_id FROM locations WHERE code = '3273060' LIMIT 1;
    IF district_id IS NULL THEN
        INSERT INTO locations (name, code, type, parent_id, lft, rght, tree_id, level)
        VALUES ('Lengkong', '3273060', 'DISTRICT', city_id, 4, 7, 1, 3) RETURNING id INTO district_id;
    END IF;
    SELECT id INTO village_id FROM locations WHERE code = '3273060001' LIMIT 1;
    IF village_id IS NULL THEN
        INSERT INTO locations (name, code, type, parent_id, lft, rght, tree_id, level)
        VALUES ('Lingkar Selatan', '3273060001', 'VILLAGE', district_id, 5, 6, 1, 4);
    END IF;
END $$;

INSERT INTO schools (name, register_number, image_data, is_active, created_at, updated_at)
VALUES
    ('ClassPing Preschool', 'CP-2026-001', NULL, TRUE, NOW(), NOW()),
    ('KB Bintang Kecil', 'CP-2026-002', NULL, TRUE, NOW(), NOW())
ON CONFLICT (register_number) DO NOTHING;

INSERT INTO school_branches (school_id, name, code, email, phone, address, location_id, is_active, created_at, updated_at)
SELECT s.id, v.name, v.code, v.email, v.phone, v.address,
       (SELECT id FROM locations WHERE code = '3273060001' LIMIT 1), TRUE, NOW(), NOW()
FROM schools s
CROSS JOIN (VALUES
    ('Main Campus', 'MAIN', 'main@classping.test', '0221234567', 'Jl. Lingkar Selatan No. 1'),
    ('North Campus', 'NORTH', 'north@classping.test', '0227654321', 'Jl. Lengkong Utara No. 10')
) AS v(name, code, email, phone, address)
WHERE s.register_number = 'CP-2026-001'
ON CONFLICT ON CONSTRAINT unique_branch_code_per_school DO NOTHING;

INSERT INTO academic_years (branch_id, name, start_date, end_date, is_current, created_at, updated_at)
SELECT b.id, v.name, v.start_date, v.end_date, v.is_current, NOW(), NOW()
FROM school_branches b
CROSS JOIN (VALUES
    ('2025/2026', DATE '2025-07-01', DATE '2026-06-30', FALSE),
    ('2026/2027', DATE '2026-07-01', DATE '2027-06-30', TRUE)
) AS v(name, start_date, end_date, is_current)
WHERE b.code = 'MAIN'
  AND NOT EXISTS (SELECT 1 FROM academic_years ay WHERE ay.branch_id = b.id AND ay.name = v.name);

-- Superadmin password is classPingAdmin; other seed-user passwords are password123.
INSERT INTO users (password, last_login, is_superuser, email, first_name, last_name, role, is_active, is_staff, created_at, updated_at)
VALUES
    ('pbkdf2_sha256$600000$classping-seed-admin$9k6HmLRDRcUclm2QyzuoU2axViyzaW0jp8LoBN6qCn0=', NULL, TRUE,  'admin@classping.test', 'System', 'Admin',   'ADMIN',   TRUE, TRUE,  NOW(), NOW()),
    ('pbkdf2_sha256$600000$classping-seed$u1DDtZQjR1pmsQjhnxItbnFdM9rgHlN/7WuitYJiusk=', NULL, FALSE, 'anna@classping.test',  'Anna',   'Teacher', 'TEACHER', TRUE, FALSE, NOW(), NOW()),
    ('pbkdf2_sha256$600000$classping-seed$u1DDtZQjR1pmsQjhnxItbnFdM9rgHlN/7WuitYJiusk=', NULL, FALSE, 'john@example.com',     'John',   'Doe',     'PARENT',  TRUE, FALSE, NOW(), NOW())
ON CONFLICT (email) DO NOTHING;

INSERT INTO staffs (branch_id, user_id, first_name, last_name, email, phone, staff_type, hire_date, qualification, is_active, created_at, updated_at)
SELECT b.id, u.id, 'Anna', 'Teacher', 'anna@classping.test', '0221234567', 'teacher', DATE '2026-01-01',
       'Bachelor of Early Childhood Education', TRUE, NOW(), NOW()
FROM school_branches b JOIN users u ON u.email = 'anna@classping.test'
WHERE b.code = 'MAIN'
ON CONFLICT (email) DO NOTHING;

INSERT INTO guardians (user_id, name, phone_number, email, image_data, created_at, updated_at)
SELECT id, 'John Doe', '081234567890', 'john@example.com', NULL, NOW(), NOW()
FROM users WHERE email = 'john@example.com'
ON CONFLICT (user_id) DO NOTHING;

INSERT INTO students (first_name, middle_name, last_name, nickname, date_of_birth, image_data, gender, address, location_id, enroll_date, status, created_at, updated_at)
SELECT v.first_name, '', v.last_name, v.nickname, v.date_of_birth, NULL, v.gender, v.address,
       (SELECT id FROM locations WHERE code = '3273060001' LIMIT 1), DATE '2026-07-01', 'active', NOW(), NOW()
FROM (VALUES
    ('Ethan', 'Doe', 'Ethan', DATE '2021-05-15', 'male',   'Jl. Lingkar Selatan No. 20'),
    ('Emma',  'Doe', 'Emma',  DATE '2020-08-20', 'female', 'Jl. Lengkong No. 30')
) AS v(first_name, last_name, nickname, date_of_birth, gender, address)
WHERE NOT EXISTS (
    SELECT 1 FROM students s WHERE s.first_name = v.first_name AND s.last_name = v.last_name AND s.date_of_birth = v.date_of_birth
);

INSERT INTO student_guardians (student_id, guardian_id, relationship, is_primary)
SELECT s.id, g.id, 'father', TRUE
FROM students s CROSS JOIN guardians g
WHERE s.first_name IN ('Ethan', 'Emma') AND s.last_name = 'Doe' AND g.email = 'john@example.com'
ON CONFLICT ON CONSTRAINT unique_student_guardian DO NOTHING;

INSERT INTO school_brach_classes (branch_id, academic_year_id, name, created_at, updated_at)
SELECT b.id, ay.id, v.name, NOW(), NOW()
FROM school_branches b
JOIN academic_years ay ON ay.branch_id = b.id AND ay.name = '2026/2027'
CROSS JOIN (VALUES ('Class A'), ('Class B'), ('Class C')) AS v(name)
WHERE b.code = 'MAIN'
ON CONFLICT ON CONSTRAINT unique_class_per_branch_academic_year DO NOTHING;

INSERT INTO class_teachers (class_id, staff_id, created_at)
SELECT c.id, st.id, NOW()
FROM school_brach_classes c CROSS JOIN staffs st
WHERE c.name IN ('Class A', 'Class B', 'Class C') AND st.email = 'anna@classping.test'
ON CONFLICT ON CONSTRAINT unique_class_teacher DO NOTHING;

INSERT INTO class_students (class_id, student_id, is_current, created_at)
SELECT c.id, s.id, TRUE, NOW()
FROM school_brach_classes c
JOIN students s ON (c.name IN ('Class A', 'Class B') AND s.first_name = 'Ethan')
                OR (c.name IN ('Class B', 'Class C') AND s.first_name = 'Emma')
WHERE c.name IN ('Class A', 'Class B', 'Class C') AND s.last_name = 'Doe'
ON CONFLICT ON CONSTRAINT unique_class_student DO NOTHING;

INSERT INTO score_settings (branch_id, name, description, score_type)
SELECT b.id, v.name, v.description, v.score_type
FROM school_branches b
CROSS JOIN (VALUES
    ('Development Level', 'Level-based scale used to assess student development.', 'LEVEL'),
    ('Numeric Assessment', 'Numeric scale used to assess student performance.', 'NUMERIC')
) AS v(name, description, score_type)
WHERE b.code = 'MAIN'
ON CONFLICT ON CONSTRAINT unique_score_setting_per_branch DO NOTHING;

INSERT INTO level_scores (score_setting_id, position, name)
SELECT ss.id, v.position, v.name
FROM score_settings ss
CROSS JOIN (VALUES (1, 'Beginning'), (2, 'Developing'), (3, 'Secure')) AS v(position, name)
WHERE ss.name = 'Development Level'
ON CONFLICT ON CONSTRAINT unique_level_score_position DO NOTHING;

INSERT INTO numeric_scores (score_setting_id, min_score, max_score)
SELECT id, 0.00, 100.00 FROM score_settings WHERE name = 'Numeric Assessment'
ON CONFLICT (score_setting_id) DO NOTHING;

INSERT INTO report_layouts (branch_id, name, description, is_system, is_active)
SELECT b.id, v.name, '', FALSE, TRUE
FROM school_branches b CROSS JOIN (VALUES ('Personal Development'), ('Montessori Progress')) AS v(name)
WHERE b.code = 'MAIN'
ON CONFLICT ON CONSTRAINT unique_report_layout_per_branch DO NOTHING;

INSERT INTO report_sections (report_layout_id, name, description, is_active)
SELECT rl.id, v.name, '', TRUE
FROM report_layouts rl
JOIN (VALUES
    ('Personal Development', 'Social Emotional'), ('Personal Development', 'Communication'),
    ('Montessori Progress', 'Practical Life'), ('Montessori Progress', 'Sensorial'), ('Montessori Progress', 'Language')
) AS v(layout_name, name) ON v.layout_name = rl.name
ON CONFLICT ON CONSTRAINT unique_report_section_per_layout DO NOTHING;

INSERT INTO indicators (report_section_id, score_setting_id, title, description)
SELECT rs.id, ss.id, v.title, ''
FROM report_sections rs
JOIN report_layouts rl ON rl.id = rs.report_layout_id AND rl.name = 'Personal Development'
JOIN score_settings ss ON ss.name = 'Development Level'
CROSS JOIN (VALUES ('Cooperation'), ('Sharing')) AS v(title)
WHERE rs.name = 'Social Emotional'
ON CONFLICT ON CONSTRAINT unique_indicator_per_report_section DO NOTHING;

INSERT INTO fee_types (branch_id, name, description, amount, is_recurring, is_active, currency, recurring_frequency, created_at, updated_at)
SELECT b.id, v.name, v.description, v.amount, v.is_recurring, TRUE, 'IDR', v.recurring_frequency, NOW(), NOW()
FROM school_branches b
CROSS JOIN (VALUES
    ('Monthly Tuition', 'Monthly tuition fee for selected classes.', 500000.00, TRUE,  'monthly'),
    ('Uniform', 'School uniform fee.', 350000.00, FALSE, NULL),
    ('Field Trip', 'Field trip contribution.', 250000.00, FALSE, NULL),
    ('Dummy Fee', 'Dummy fee used for payment and invoice testing.', 500000.00, TRUE, 'monthly')
) AS v(name, description, amount, is_recurring, recurring_frequency)
WHERE b.code = 'MAIN'
ON CONFLICT ON CONSTRAINT unique_fee_type_per_branch DO UPDATE
SET description = EXCLUDED.description, amount = EXCLUDED.amount, is_recurring = EXCLUDED.is_recurring,
    currency = EXCLUDED.currency, recurring_frequency = EXCLUDED.recurring_frequency, updated_at = NOW();

INSERT INTO fee_type_classes (fee_type_id, class_id, created_at)
SELECT ft.id, c.id, NOW()
FROM fee_types ft JOIN school_brach_classes c ON c.name IN ('Class A', 'Class B')
WHERE ft.name IN ('Monthly Tuition', 'Dummy Fee')
ON CONFLICT ON CONSTRAINT unique_fee_type_class DO NOTHING;

-- Mirrors seed_billing(): use the first two ClassStudent rows for Main Campus.
WITH selected_class_students AS (
    SELECT cs.id
    FROM class_students cs
    JOIN school_brach_classes c ON c.id = cs.class_id
    JOIN school_branches b ON b.id = c.branch_id
    WHERE b.code = 'MAIN'
    ORDER BY cs.id
    LIMIT 2
)
UPDATE class_students cs SET is_current = TRUE
FROM selected_class_students selected
WHERE cs.id = selected.id;

WITH selected_class_students AS (
    SELECT cs.id AS class_student_id, cs.student_id, cs.class_id,
           ROW_NUMBER() OVER (ORDER BY cs.id) AS row_number
    FROM class_students cs
    JOIN school_brach_classes c ON c.id = cs.class_id
    JOIN school_branches b ON b.id = c.branch_id
    WHERE b.code = 'MAIN'
    ORDER BY cs.id
    LIMIT 2
), dummy_fee AS (
    SELECT id, amount, currency FROM fee_types WHERE name = 'Dummy Fee' LIMIT 1
)
INSERT INTO student_invoices (invoice_no, invoice_date, due_date, status, subtotal, tax_amount, total_amount, currency, total_discount, amount_paid, remark, class_student_id, fee_type_id, fee_type_class_id, created_at, updated_at)
SELECT CASE selected.row_number
           WHEN 1 THEN 'INV-SEED-UNPAID-' || selected.student_id
           WHEN 2 THEN 'INV-SEED-OVERDUE-' || selected.student_id
       END,
       CASE WHEN selected.row_number = 1 THEN CURRENT_DATE ELSE CURRENT_DATE - 30 END,
       CASE WHEN selected.row_number = 1 THEN CURRENT_DATE + 14 ELSE CURRENT_DATE - 5 END,
       CASE WHEN selected.row_number = 1 THEN 'unpaid' ELSE 'overdue' END,
       fee.amount, 0.00, fee.amount, fee.currency, 0.00, 0.00,
       'Seed invoice for payment flow testing.', selected.class_student_id, fee.id, fee_class.id, NOW(), NOW()
FROM selected_class_students selected
CROSS JOIN dummy_fee fee
LEFT JOIN fee_type_classes fee_class ON fee_class.fee_type_id = fee.id AND fee_class.class_id = selected.class_id
ON CONFLICT (invoice_no) DO UPDATE
SET invoice_date = EXCLUDED.invoice_date, due_date = EXCLUDED.due_date, status = EXCLUDED.status,
    class_student_id = EXCLUDED.class_student_id, fee_type_class_id = EXCLUDED.fee_type_class_id,
    updated_at = NOW();

COMMIT;
