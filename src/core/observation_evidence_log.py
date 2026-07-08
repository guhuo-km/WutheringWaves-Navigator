from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable


LogLine = tuple[str, str]


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _fmt_candidate(name: str, candidate: dict[str, Any] | None) -> list[str]:
    if not candidate:
        return [f"  {name}: (none)"]
    return [
        f"  {name}: x={candidate.get('x')} y={candidate.get('y')} z={candidate.get('z')}",
        f"    source={candidate.get('source', '')} confidence={candidate.get('confidence')}",
        f"    reason={candidate.get('reason', '')}",
    ]


def _fmt_match_evidence(name: str, evidence: dict[str, Any] | None) -> list[str]:
    if not isinstance(evidence, dict):
        return [f"  {name}: (none)"]
    return [
        f"  {name}: location={evidence.get('location')} raw_score={evidence.get('raw_score')} "
        f"confidence={evidence.get('normalized_confidence')}"
    ]


def _fmt_visual_trace(trace: dict[str, Any] | None) -> list[str]:
    if not isinstance(trace, dict):
        return []
    if trace.get("rough_index_source") == "tile_index":
        lines = [
            "  visual_trace:",
            "    tile_index: "
            f"rough_candidates_available={trace.get('rough_candidates_available')} "
            f"used={trace.get('rough_candidates_used')} "
            f"skipped_missing={trace.get('rough_candidates_skipped_missing')}",
        ]
        hits = trace.get("rough_hits")
        if isinstance(hits, list):
            for hit in hits:
                if not isinstance(hit, dict):
                    continue
                tile_keys = hit.get("tile_keys")
                tile_text = ",".join(str(value) for value in tile_keys) if isinstance(tile_keys, list) else ""
                lines.append(
                    f"      hit rank={hit.get('rank')} score={hit.get('score')} "
                    f"work_key={hit.get('work_key')}"
                )
                lines.append(f"        tiles={tile_text}")
                lines.append(
                    f"        sift_index={hit.get('sift_index_source')} features={hit.get('feature_count')} "
                    f"raw={hit.get('raw_match_count')} good={hit.get('good_match_count')} "
                    f"inliers={hit.get('inlier_count')} accepted={hit.get('accepted')} "
                    f"skip={hit.get('skip_reason', '')}"
                )
        return lines
    manifests = trace.get("manifests")
    if not isinstance(manifests, list) or not manifests:
        return []
    lines = ["  visual_trace:"]
    for manifest in manifests:
        if not isinstance(manifest, dict):
            continue
        lines.append(
            f"    manifest area={manifest.get('area_id')} type={manifest.get('candidate_type')} "
            f"layer={manifest.get('layer_id')} z={manifest.get('z_level')} "
            f"rough_index={manifest.get('rough_index_source')}"
        )
        hits = manifest.get("rough_hits")
        if not isinstance(hits, list):
            continue
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            window = hit.get("window") if isinstance(hit.get("window"), dict) else {}
            tile_keys = hit.get("tile_keys")
            if isinstance(tile_keys, list):
                tile_text = ",".join(str(value) for value in tile_keys)
            else:
                tile_text = ""
            lines.append(
                f"      hit rank={hit.get('rank')} score={hit.get('score')} "
                f"window=({window.get('left')},{window.get('top')},{window.get('width')},{window.get('height')})"
            )
            lines.append(f"        tiles={tile_text}")
            lines.append(
                f"        sift_index={hit.get('sift_index_source')} features={hit.get('feature_count')} "
                f"raw={hit.get('raw_match_count')} good={hit.get('good_match_count')} "
                f"inliers={hit.get('inlier_count')} accepted={hit.get('accepted')}"
            )
    return lines


def format_decision_system_line(bundle: dict[str, Any]) -> str | None:
    decision = bundle.get("decision")
    if not isinstance(decision, dict):
        return None
    reason = decision.get("reason", "")
    coord = decision.get("coord")
    source = decision.get("source", "")
    if coord is None and reason in ("", "no_candidate"):
        return None
    return f"[{_ts()}] [OBS-DECISION] coord={coord} source={source} reason={reason}"


def format_observation_ocr_block(bundle: dict[str, Any]) -> list[str]:
    lines = [f"[{_ts()}] [OBS-EVIDENCE] --- observation cycle ---"]
    lines.extend(_fmt_candidate("ocr", bundle.get("ocr")))
    lines.extend(_fmt_candidate("visual", bundle.get("visual")))
    visual_result = bundle.get("visual_result")
    if isinstance(visual_result, dict):
        manifest = visual_result.get("manifest")
        manifest = manifest if isinstance(manifest, dict) else {}
        lines.append(
            f"  visual_match: area={manifest.get('area_id')} type={manifest.get('candidate_type')} "
            f"layer={manifest.get('layer_id')} z={manifest.get('z_level')}"
        )
        lines.extend(_fmt_match_evidence("rough", visual_result.get("rough")))
        lines.extend(_fmt_match_evidence("exact", visual_result.get("exact")))
    lines.extend(_fmt_visual_trace(bundle.get("visual_trace")))
    failure_reason = bundle.get("visual_failure_reason")
    if failure_reason:
        lines.append(f"  visual_failure_reason={failure_reason}")
    error = bundle.get("error")
    if error:
        lines.append(f"  error={error}")
    if "previous_coordinate" in bundle:
        lines.append(f"  previous_coordinate={bundle.get('previous_coordinate')}")
    frame_package_path = bundle.get("frame_package_path")
    if frame_package_path:
        lines.append(f"  frame_package={frame_package_path}")
    timings = bundle.get("timings_ms")
    if isinstance(timings, dict):
        lines.append(
            "  timings_ms: "
            f"normalize={timings.get('normalize_minimap')} "
            f"heading={timings.get('heading')} "
            f"visual={timings.get('visual')} "
            f"decision={timings.get('decision')} "
            f"total={timings.get('total')}"
        )
    heading = bundle.get("heading")
    if isinstance(heading, dict):
        lines.append(
            f"  heading: angle={heading.get('angle_degrees')} bucket={heading.get('bucket')} "
            f"confidence={heading.get('confidence')}"
        )
    else:
        lines.append("  heading: (none)")
        heading_failure_reason = bundle.get("heading_failure_reason")
        if heading_failure_reason:
            lines.append(f"  heading_failure_reason={heading_failure_reason}")
    decision = bundle.get("decision") if isinstance(bundle.get("decision"), dict) else {}
    lines.append(
        f"  decision: coord={decision.get('coord')} source={decision.get('source')} "
        f"reason={decision.get('reason', '')}"
    )
    lines.append(f"[{_ts()}] [OBS-EVIDENCE] --- end ---")
    return lines


def route_observation_bundle(
    bundle: dict[str, Any],
    *,
    detailed_debug: bool,
) -> Iterable[LogLine]:
    system_line = format_decision_system_line(bundle)
    if system_line:
        yield ("system", system_line)
    if detailed_debug:
        for line in format_observation_ocr_block(bundle):
            yield ("recognition", line)
