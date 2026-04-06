locals {
  bucket_prefix = "yeet-obs-${var.environment}"
}

# ── Loki S3 bucket ─────────────────────────────────���──────────────────────────
resource "aws_s3_bucket" "loki" {
  bucket = "${local.bucket_prefix}-loki"
}

resource "aws_s3_bucket_versioning" "loki" {
  bucket = aws_s3_bucket.loki.id
  versioning_configuration { status = "Disabled" }
}

resource "aws_s3_bucket_lifecycle_configuration" "loki" {
  bucket = aws_s3_bucket.loki.id
  rule {
    id     = "loki-tiering"
    status = "Enabled"
    transition {
      days          = 30
      storage_class = "GLACIER_IR"
    }
    expiration {
      days = 365
    }
  }
}

# ── Tempo S3 bucket ─────────────────────────────────���─────────────────────────
resource "aws_s3_bucket" "tempo" {
  bucket = "${local.bucket_prefix}-tempo"
}

resource "aws_s3_bucket_lifecycle_configuration" "tempo" {
  bucket = aws_s3_bucket.tempo.id
  rule {
    id     = "tempo-tiering"
    status = "Enabled"
    transition {
      days          = 7
      storage_class = "GLACIER_IR"
    }
    expiration {
      days = 30
    }
  }
}

# ── Thanos S3 bucket ───────────────────────────────��──────────────────────────
resource "aws_s3_bucket" "thanos" {
  bucket = "${local.bucket_prefix}-thanos"
}

resource "aws_s3_bucket_lifecycle_configuration" "thanos" {
  bucket = aws_s3_bucket.thanos.id
  rule {
    id     = "thanos-tiering"
    status = "Enabled"
    transition {
      days          = 90
      storage_class = "GLACIER_IR"
    }
    expiration {
      days = 400
    }
  }
}

# ── Block all public access on all buckets ────────────────────────────────────
resource "aws_s3_bucket_public_access_block" "loki" {
  bucket                  = aws_s3_bucket.loki.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_public_access_block" "tempo" {
  bucket                  = aws_s3_bucket.tempo.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_public_access_block" "thanos" {
  bucket                  = aws_s3_bucket.thanos.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

output "loki_bucket_id"   { value = aws_s3_bucket.loki.id }
output "tempo_bucket_id"  { value = aws_s3_bucket.tempo.id }
output "thanos_bucket_id" { value = aws_s3_bucket.thanos.id }

variable "environment" {}
variable "aws_region"  { default = "us-east-1" }
