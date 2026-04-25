-- Reference SQL — generated from Prisma schema (do not edit manually)
-- Applied to: fc_prod via `npx prisma db push`
-- To re-apply: npx prisma db push

CREATE TABLE IF NOT EXISTS "users" (
  "id"            TEXT         NOT NULL,
  "email"         TEXT         NOT NULL,
  "name"          TEXT,
  "password_hash" TEXT         NOT NULL,
  "created_at"    TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updated_at"    TIMESTAMP(3) NOT NULL,

  CONSTRAINT "users_pkey" PRIMARY KEY ("id")
);

CREATE UNIQUE INDEX IF NOT EXISTS "users_email_key" ON "users"("email");

CREATE TABLE IF NOT EXISTS "password_resets" (
  "id"         TEXT         NOT NULL,
  "user_id"    TEXT         NOT NULL,
  "token_hash" TEXT         NOT NULL,
  "expires_at" TIMESTAMP(3) NOT NULL,
  "used_at"    TIMESTAMP(3),
  "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CONSTRAINT "password_resets_pkey"             PRIMARY KEY ("id"),
  CONSTRAINT "password_resets_user_id_fkey"
    FOREIGN KEY ("user_id") REFERENCES "users"("id")
    ON UPDATE CASCADE ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS "password_resets_token_hash_key" ON "password_resets"("token_hash");
CREATE        INDEX IF NOT EXISTS "password_resets_user_id_idx"    ON "password_resets"("user_id");
