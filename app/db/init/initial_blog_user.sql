USE blog_db;
SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS `blogs`;
DROP TABLE IF EXISTS `users`;
DROP TABLE IF EXISTS `outbox`;


CREATE TABLE `users`(
    `id` INT NOT NULL AUTO_INCREMENT,
    `name` VARCHAR(100) NOT NULL,
    `email` VARCHAR(100) NOT NULL,
    `password` VARCHAR(255) NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_users_email` (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `blogs` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `title` VARCHAR(200) NOT NULL,
    `author_id` INT NOT NULL,
    `content` TEXT NOT NULL,
    `image_loc` VARCHAR(400) NULL,
    `modified_dt` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_author_id` (`author_id`),
    KEY `idx_modified_id` (`modified_dt`, `id`),
    CONSTRAINT `fk_blogs_author_id` FOREIGN KEY (`author_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;


CREATE TABLE `outbox` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `event_type` VARCHAR(40) NOT NULL,
    `aggregate_id` BIGINT NOT NULL,
    `payload` JSON NULL,
    `status` VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    `retry_count` SMALLINT NOT NULL DEFAULT 0,
    `next_retry_at` DATETIME NULL,
    `locked_at` DATETIME NULL,
    `processed_at` DATETIME NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_status_retry_id` (`status`, `next_retry_at`, `id`),
    KEY `idx_processed_at` (`processed_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

