import json

import pytest

from supplier_seed.operations.local_deployment_certification import (
    CertificationFailure,
    run_local_deployment_certification,
)


def test_r3_s3_certifies_real_local_runtime_and_restart(tmp_path):
    output_dir = tmp_path / "r3-s3-evidence"

    report = run_local_deployment_certification(output_dir)

    assert report["certified"] is True
    assert report["local_only"] is True
    assert report["production_activation_approved"] is False
    assert report["inventory_base44_changed"] is False
    assert report["evidence"]["supplier_count_before_restart"] == 1
    assert report["evidence"]["supplier_count_after_restart"] == 1
    assert report["evidence"]["governance_event_count_before_restart"] > 0
    assert report["evidence"]["idempotency_receipt_count_before_restart"] > 0
    assert report["evidence"]["replay_status"] == 202
    assert report["evidence"]["changed_payload_status"] == 409
    assert report["evidence"]["nonce_replay_status"] == 401
    assert report["evidence"]["public_v1_post_status"] == 405
    assert all(check["passed"] for check in report["checks"])

    persisted_report = json.loads((output_dir / "r3-s3-certification-report.json").read_text(encoding="utf-8"))
    assert persisted_report["certified"] is True
    assert persisted_report["evidence"]["supplier_id"]


def test_r3_s3_refuses_to_delete_or_reuse_nonempty_evidence_directory(tmp_path):
    output_dir = tmp_path / "existing"
    output_dir.mkdir()
    marker = output_dir / "do-not-delete.txt"
    marker.write_text("preserve me", encoding="utf-8")

    with pytest.raises(CertificationFailure):
        run_local_deployment_certification(output_dir)

    assert marker.read_text(encoding="utf-8") == "preserve me"
