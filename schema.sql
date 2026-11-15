-- =====================================================================
-- Lost & Found+ — MySQL schema
-- Safe to re-run: every statement uses CREATE ... IF NOT EXISTS.
-- Existing rows are never dropped.
-- =====================================================================

CREATE DATABASE IF NOT EXISTS lost_and_found_plus
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE lost_and_found_plus;

CREATE TABLE IF NOT EXISTS users (
    user_id     INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    email       VARCHAR(150) NOT NULL UNIQUE,
    password    VARCHAR(255) NOT NULL,
    role        VARCHAR(20) NOT NULL DEFAULT 'user',
    student_id  VARCHAR(50),
    department  VARCHAR(100),
    phone       VARCHAR(20),
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_users_role (role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS item_reports (
    item_id            INT AUTO_INCREMENT PRIMARY KEY,
    user_id            INT NOT NULL,
    item_name          VARCHAR(200) NOT NULL,
    category           VARCHAR(100) NOT NULL,
    item_type          VARCHAR(10) NOT NULL,
    description        TEXT,
    color              VARCHAR(50),
    brand              VARCHAR(100),
    location           VARCHAR(200),
    distinctive_marks  TEXT,
    item_date          DATE NOT NULL,
    image              VARCHAR(500),
    status             VARCHAR(20) NOT NULL DEFAULT 'Active',
    is_returned        TINYINT(1) NOT NULL DEFAULT 0,
    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_items_user FOREIGN KEY (user_id)
        REFERENCES users(user_id) ON DELETE CASCADE,
    CONSTRAINT chk_item_type CHECK (item_type IN ('Lost', 'Found')),
    INDEX idx_item_type (item_type),
    INDEX idx_category (category),
    INDEX idx_status (status),
    INDEX idx_is_returned (is_returned),
    INDEX idx_item_date (item_date),
    INDEX idx_items_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS claims (
    claim_id             INT AUTO_INCREMENT PRIMARY KEY,
    claimant_id          INT NOT NULL,
    item_id              INT NOT NULL,
    message              TEXT,
    verification_details TEXT,
    status               VARCHAR(20) NOT NULL DEFAULT 'Pending',
    admin_response       TEXT,
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_claims_user FOREIGN KEY (claimant_id)
        REFERENCES users(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_claims_item FOREIGN KEY (item_id)
        REFERENCES item_reports(item_id) ON DELETE CASCADE,
    CONSTRAINT chk_claim_status
        CHECK (status IN ('Pending', 'Approved', 'Rejected', 'Completed')),
    INDEX idx_claims_status (status),
    INDEX idx_claims_item (item_id),
    INDEX idx_claims_user (claimant_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS matches (
    match_id      INT AUTO_INCREMENT PRIMARY KEY,
    lost_item_id  INT NOT NULL,
    found_item_id INT NOT NULL,
    match_score   DECIMAL(5,2) NOT NULL,
    match_reasons TEXT,
    status        VARCHAR(20) NOT NULL DEFAULT 'Active',
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_match_lost FOREIGN KEY (lost_item_id)
        REFERENCES item_reports(item_id) ON DELETE CASCADE,
    CONSTRAINT fk_match_found FOREIGN KEY (found_item_id)
        REFERENCES item_reports(item_id) ON DELETE CASCADE,
    UNIQUE KEY uq_match_pair (lost_item_id, found_item_id),
    INDEX idx_match_score (match_score),
    INDEX idx_match_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS notifications (
    notification_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id         INT NOT NULL,
    match_id        INT NULL,
    message         VARCHAR(500) NOT NULL,
    is_read         TINYINT(1) NOT NULL DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_notifications_user FOREIGN KEY (user_id)
        REFERENCES users(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_notifications_match FOREIGN KEY (match_id)
        REFERENCES matches(match_id) ON DELETE CASCADE,
    INDEX idx_notifications_user (user_id, is_read)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
