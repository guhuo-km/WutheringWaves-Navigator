import json
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FULL_SCRIPT = PROJECT_ROOT / "js" / "wuwa_map_optimizer.js"
LITE_SCRIPT = PROJECT_ROOT / "js" / "wuwa_map_optimizer_lite.js"


def scripts() -> list[str]:
    return [
        FULL_SCRIPT.read_text(encoding="utf-8"),
        LITE_SCRIPT.read_text(encoding="utf-8"),
    ]


def extract_js_declaration(text: str, declaration: str) -> str:
    start = text.index(f"    {declaration}")
    end = text.index(";", start) + 1
    return text[start:end]


def extract_js_function(text: str, name: str) -> str:
    start = text.index(f"    function {name}(")
    next_function = text.find("\n    function ", start + 1)
    if next_function < 0:
        raise AssertionError(f"cannot find end of JavaScript function {name}")
    return text[start:next_function]


def run_graph_data_harness(script_path: Path) -> dict:
    text = script_path.read_text(encoding="utf-8")
    declarations = [
        extract_js_declaration(text, "const ROUTE_GRAPH_SCHEMA ="),
        extract_js_declaration(text, "const ROUTE_GRAPH_VERSION ="),
        extract_js_declaration(text, "const SPECIAL_MARKER_SHAPES ="),
        extract_js_declaration(text, "const DEFAULT_SPECIAL_MARKER_STYLE ="),
    ]
    functions = [
        "normalizeRouteCoordinate",
        "normalizeHexColor",
        "hexToRgb",
        "rgbToHex",
        "rgbToHsv",
        "hsvToRgb",
        "clampNumber",
        "normalizeSpecialMarkerStyle",
        "createSpecialMarkerStyleDraft",
        "restoreSpecialMarkerGroupStyle",
        "normalizeSpecialMarkerGroups",
        "renderSpecialMarkerGroups",
        "makeGraphNodeId",
        "makeGraphEdgeId",
        "pointToGraphNode",
        "normalizeRouteAssociatedMarkers",
        "isRouteGraphV2",
        "getLegacyRouteSegments",
        "normalizeLegacyRouteGraph",
        "normalizeRouteGraph",
        "serializeRouteGraph",
        "createEmptyRouteGraph",
        "removeNodeFromSpecialMarkerGroups",
        "createSpecialMarkerGroupId",
        "addNodeToSpecialMarkerGroup",
        "removeNodeFromSpecialMarkerGroup",
        "moveSpecialMarkerGroupMember",
        "deleteSpecialMarkerGroup",
        "deleteGraphNode",
        "setExclusiveGraphEditMode",
        "createEditNodeIcon",
    ]
    source = "\n".join([*declarations, *(extract_js_function(text, name) for name in functions)])
    harness = f"""
{source}
const rawV2 = {{
    schema: ROUTE_GRAPH_SCHEMA,
    version: ROUTE_GRAPH_VERSION,
    route_info: {{ name: 'v2' }},
    nodes: [
        {{ id: 'n1', x: 10.6, y: '20.2', z: -1.6, labelStyle: 'badge', markerStyle: 'star', color: '#123456' }},
        {{ id: 'n2', x: 30.4, y: 40.5, z: 2.2 }},
        {{ id: 'n3', x: 50, y: 60, z: 3 }}
    ],
    edges: [{{ id: 'e1', from: 'n1', to: 'n2' }}],
    special_marker_groups: [
        {{
            id: 'g1',
            style: {{
                shape: 'star',
                fill_color: '#abcdef',
                number: {{
                    font_size: 30,
                    color: '#010203',
                    outline: {{ enabled: false, width: 3, color: '#aabbcc' }}
                }}
            }},
            node_ids: ['n2', 'missing', 'n1', 'n2']
        }},
        {{ id: 'g2', style: {{ shape: 'circle' }}, node_ids: ['n1', 'n3'] }},
        {{ id: 'empty', node_ids: [] }}
    ]
}};
const v2 = normalizeRouteGraph(rawV2, 'fallback');
const withoutGroups = normalizeRouteGraph({{
    schema: ROUTE_GRAPH_SCHEMA,
    version: ROUTE_GRAPH_VERSION,
    nodes: [{{ id: 'n1', x: 1, y: 2, z: 3 }}],
    edges: []
}});
const serialized = serializeRouteGraph({{ name: 'v2', editingGraph: v2 }});
const consecutive = normalizeLegacyRouteGraph({{
    points: [
        {{ x: 0.2, y: 0.2, z: 0.2 }},
        {{ x: 10.4, y: 10.4, z: 1.6 }},
        {{ x: 10.49, y: 10.49, z: 9.2 }},
        {{ x: 10.1, y: 10.1, z: -4.8 }},
        {{ x: 20.2, y: 20.2, z: 3.4 }}
    ]
}}, 'legacy');
const revisited = normalizeLegacyRouteGraph({{
    points: [
        {{ x: 100, y: 200, z: 0 }},
        {{ x: 120, y: 220, z: 0 }},
        {{ x: 100, y: 200, z: 0 }}
    ]
}}, 'legacy');
const segmented = normalizeLegacyRouteGraph({{
    routes: [
        {{ points: [{{ x: 1, y: 1, z: 0 }}, {{ x: 2, y: 2, z: 0 }}] }},
        {{ points: [{{ x: 2, y: 2, z: 0 }}, {{ x: 3, y: 3, z: 0 }}] }}
    ]
}}, 'segments');
const renderCalls = [];
const L = {{
    divIcon: options => options,
    marker: (latlng, options) => ({{
        addTo: () => {{
            renderCalls.push({{ latlng, html: options.icon.html }});
        }}
    }})
}};
function gameToLatLng(x, y) {{ return [x, y]; }}
let removedPreviewCount = 0;
let refreshCount = 0;
const STATE = {{ mapInstance: {{ closePopup() {{}} }} }};
function installRouteMarkerAssociationCapture() {{}}
function scheduleRouteMarkerDisplay() {{}}
function syncGraphBoxSelectionMapDrag() {{}}
function refreshGraphEditRoute() {{ refreshCount += 1; }}
function closeSpecialMarkerStyleModal() {{ return false; }}
function removeEditConnectionPreview(route) {{
    removedPreviewCount += 1;
    route.connectionPreview = null;
}}
renderSpecialMarkerGroups({{}}, v2);
const regularRenderCount = renderCalls.length;
const shapeGraph = normalizeRouteGraph({{
    schema: ROUTE_GRAPH_SCHEMA,
    version: ROUTE_GRAPH_VERSION,
    nodes: [
        {{ id: 'sd', x: 1, y: 1, z: 0 }},
        {{ id: 'ss', x: 2, y: 2, z: 0 }},
        {{ id: 'st', x: 3, y: 3, z: 0 }},
        {{ id: 'sc', x: 4, y: 4, z: 0 }}
    ],
    edges: [],
    special_marker_groups: [
        {{ id: 'gd', style: {{ shape: 'diamond' }}, node_ids: ['sd'] }},
        {{ id: 'gs', style: {{ shape: 'star' }}, node_ids: ['ss'] }},
        {{ id: 'gt', style: {{ shape: 'triangle-up' }}, node_ids: ['st'] }},
        {{ id: 'gc', style: {{ shape: 'circle' }}, node_ids: ['sc'] }}
    ]
}});
renderSpecialMarkerGroups({{}}, shapeGraph);
const deleteRoute = {{
    editingGraph: JSON.parse(JSON.stringify(v2)),
    pendingConnectFromNodeId: null,
    graphSelectedIds: new Set(),
    graphSelectionType: null
}};
deleteGraphNode(deleteRoute, 'n1');
const groupGraph = {{
    nodes: [
        {{ id: 'n1', x: 1, y: 1, z: 0 }},
        {{ id: 'n2', x: 2, y: 2, z: 0 }},
        {{ id: 'n3', x: 3, y: 3, z: 0 }}
    ],
    edges: [],
    special_marker_groups: [
        {{ id: 'smg1', node_ids: ['n1', 'n2'] }},
        {{ id: 'smg3', node_ids: ['n3'] }},
        {{ id: 'empty', node_ids: [] }}
    ]
}};
const firstCreatedGroupId = createSpecialMarkerGroupId(groupGraph);
const repeatedCreatedGroupId = createSpecialMarkerGroupId(groupGraph);
groupGraph.special_marker_groups.push({{ id: firstCreatedGroupId, node_ids: [] }});
const nextCreatedGroupId = createSpecialMarkerGroupId(groupGraph);
const groupRoute = {{ editingGraph: JSON.parse(JSON.stringify(groupGraph)) }};
const beforeInvalidAdds = JSON.stringify(groupRoute.editingGraph.special_marker_groups);
const invalidAddResults = [
    addNodeToSpecialMarkerGroup(groupRoute, 'missing', 'n2'),
    addNodeToSpecialMarkerGroup(groupRoute, 'smg1', 'missing'),
    addNodeToSpecialMarkerGroup(groupRoute, 'smg1', 'n1')
];
const afterInvalidAdds = JSON.stringify(groupRoute.editingGraph.special_marker_groups);
const movedBetweenGroups = addNodeToSpecialMarkerGroup(groupRoute, 'smg1', 'n3');
const afterMoveBetweenGroups = JSON.parse(JSON.stringify(groupRoute.editingGraph.special_marker_groups));
const duplicateAdd = addNodeToSpecialMarkerGroup(groupRoute, 'smg1', 'n3');
const removedMember = removeNodeFromSpecialMarkerGroup(groupRoute, 'smg1', 'n2');
const removedMissingMember = removeNodeFromSpecialMarkerGroup(groupRoute, 'smg1', 'n2');
const movedUp = moveSpecialMarkerGroupMember(groupRoute, 'smg1', 'n3', 'up');
const movePastTop = moveSpecialMarkerGroupMember(groupRoute, 'smg1', 'n3', 'up');
const movedDown = moveSpecialMarkerGroupMember(groupRoute, 'smg1', 'n3', 'down');
const movePastBottom = moveSpecialMarkerGroupMember(groupRoute, 'smg1', 'n3', 'down');
const beforeDeleteNodeIds = groupRoute.editingGraph.nodes.map(node => node.id);
const deletedGroup = deleteSpecialMarkerGroup(groupRoute, 'smg1');
const deletedMissingGroup = deleteSpecialMarkerGroup(groupRoute, 'missing');
const modeRoute = {{
    pendingConnectFromNodeId: 'n1',
    connectionPreview: {{}},
    specialMarkerAddingGroupId: 'smg1',
    specialMarkerSelectedGroupId: 'smg1',
    graphSelectionType: 'node',
    graphSelectedIds: new Set(['n1'])
}};
setExclusiveGraphEditMode(modeRoute, 'special-groups');
const afterEnterGroupMode = {{
    specialMarkerGroupMode: modeRoute.specialMarkerGroupMode,
    specialMarkerAddingGroupId: modeRoute.specialMarkerAddingGroupId,
    pendingConnectFromNodeId: modeRoute.pendingConnectFromNodeId,
    connectionPreview: modeRoute.connectionPreview,
    graphSelectionType: modeRoute.graphSelectionType,
    graphSelectedIds: Array.from(modeRoute.graphSelectedIds)
}};
modeRoute.specialMarkerAddingGroupId = 'smg2';
setExclusiveGraphEditMode(modeRoute, 'selection');
const afterSwitchMode = JSON.parse(JSON.stringify(modeRoute));
modeRoute.specialMarkerAddingGroupId = 'smg3';
setExclusiveGraphEditMode(modeRoute, 'selection', false);
const afterExitMode = JSON.parse(JSON.stringify(modeRoute));
const coordinateNode = {{ id: 'n1', x: 10.6, y: '20.2', z: 0 }};
const groupedNodeIcon = createEditNodeIcon(0, coordinateNode, 12, {{ specialMarkerGroupMode: true }});
const regularNodeIcon = createEditNodeIcon(0, coordinateNode, 12, {{ specialMarkerGroupMode: false }});
const colorSamples = ['#000000', '#FFFFFF', '#E06474', '#12ABEF'].map(hex => {{
    const rgb = hexToRgb(hex);
    const hsv = rgbToHsv(rgb.r, rgb.g, rgb.b);
    return {{ hex, rgb, hsv, roundTrip: rgbToHex(...Object.values(hsvToRgb(hsv.h, hsv.s, hsv.v))) }};
}});
const styleRoute = {{
    editingGraph: {{
        special_marker_groups: [{{
            id: 'style-group',
            style: normalizeSpecialMarkerStyle({{
                shape: 'star',
                fill_color: '#123456',
                number: {{
                    font_size: 31,
                    color: '#ABCDEF',
                    outline: {{ enabled: false, width: 4, color: '#654321' }}
                }}
            }})
        }}]
    }}
}};
const styleSnapshot = createSpecialMarkerStyleDraft(styleRoute.editingGraph.special_marker_groups[0].style);
styleRoute.editingGraph.special_marker_groups[0].style.fill_color = '#FFFFFF';
styleRoute.editingGraph.special_marker_groups[0].style.number.outline.width = 8;
const restoredStyle = restoreSpecialMarkerGroupStyle(styleRoute, 'style-group', styleSnapshot);
process.stdout.write(JSON.stringify({{
    shapes: SPECIAL_MARKER_SHAPES,
    v2,
    withoutGroups,
    serialized,
    empty: createEmptyRouteGraph('empty'),
    consecutive,
    revisited,
    segmented,
    renderCalls: renderCalls.slice(0, regularRenderCount),
    shapeRenderCalls: renderCalls.slice(regularRenderCount),
    afterDeleteGroups: deleteRoute.editingGraph.special_marker_groups,
    groupOperations: {{
        firstCreatedGroupId,
        repeatedCreatedGroupId,
        nextCreatedGroupId,
        invalidAddResults,
        invalidAddsUnchanged: beforeInvalidAdds === afterInvalidAdds,
        movedBetweenGroups,
        afterMoveBetweenGroups,
        duplicateAdd,
        removedMember,
        removedMissingMember,
        movedUp,
        movePastTop,
        movedDown,
        movePastBottom,
        deletedGroup,
        deletedMissingGroup,
        remainingGroups: groupRoute.editingGraph.special_marker_groups,
        beforeDeleteNodeIds,
        afterDeleteNodeIds: groupRoute.editingGraph.nodes.map(node => node.id)
    }},
    modeOperations: {{
        afterEnterGroupMode,
        afterSwitchMode,
        afterExitMode,
        removedPreviewCount,
        refreshCount
    }},
    editNodeIcons: {{ grouped: groupedNodeIcon.html, regular: regularNodeIcon.html }},
    colorSamples,
    invalidHex: hexToRgb('#12345'),
    normalizedRgbHex: rgbToHex(300, -20, 15.6),
    styleDraft: {{
        snapshot: styleSnapshot,
        restored: restoredStyle,
        current: styleRoute.editingGraph.special_marker_groups[0].style,
        detached: styleSnapshot !== styleRoute.editingGraph.special_marker_groups[0].style
    }}
}}));
"""
    result = subprocess.run(
        ["node", "-"],
        input=harness,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_graph_constants_and_helpers_exist_in_both_scripts():
    for text in scripts():
        assert "ROUTE_GRAPH_SCHEMA = 'wuwa-route-graph'" in text
        assert "ROUTE_GRAPH_VERSION = 2" in text
        assert "function makeGraphNodeId(index)" in text
        assert "function makeGraphEdgeId(index)" in text
        assert "function normalizeRouteGraph(rawData, routeName = 'route')" in text
        assert "function normalizeLegacyRouteGraph(rawData, routeName)" in text
        assert "function serializeRouteGraph(route)" in text


def test_associated_official_markers_are_preserved_by_both_route_serializers():
    for text in scripts():
        assert "function normalizeRouteAssociatedMarkers(rawData)" in text
        assert "associated_markers: normalizeRouteAssociatedMarkers(rawData)" in text
        assert "associated_markers: normalizeRouteAssociatedMarkers(graph)" in text
        assert "associated_markers: []" in text


def test_official_route_marker_controls_exist_only_in_full_script():
    full = FULL_SCRIPT.read_text(encoding="utf-8")
    lite = LITE_SCRIPT.read_text(encoding="utf-8")

    assert "markerDisplayMode: getRouteMarkerDisplayMode()" in full
    assert 'id="sm-route-marker-display-mode"' in full
    assert 'data-route-marker-mode="none"' in full
    assert 'data-route-marker-mode="highlight"' in full
    assert 'data-route-marker-mode="focus"' in full
    assert 'id="kmp-toolbar-route-markers"' in full
    assert "function installRouteMarkerAssociationCapture()" in full
    assert "function toggleRouteAssociatedMarker(route, markerRecord)" in full
    assert "function applyRouteMarkerDisplay(reason)" in full
    assert "function hasVisibleJsonRoute()" in full
    assert "applyMarkerFocusByKeys(keys, 'route'" in full
    assert "STATE.markerFocus.keepKeys.size === 0 && STATE.markerFocus.owner !== 'route'" in full

    assert "sm-route-marker-display-mode" not in lite
    assert "kmp-toolbar-route-markers" not in lite
    assert "installRouteMarkerAssociationCapture" not in lite
    assert "applyRouteMarkerDisplay" not in lite


def test_official_route_marker_association_uses_canvas_renderer_hit_testing():
    full = FULL_SCRIPT.read_text(encoding="utf-8")

    assert "function findOfficialMarkerHitByCanvas(target)" in full
    assert "function buildOfficialMarkerRecord(typeId, pointId, controller)" in full
    assert "Object.values(mapStore.mapInstance._layers)" in full
    assert "layer && layer._container === target" in full
    assert "const hoveredLayer = renderer && renderer._hoveredLayer" in full
    assert "controller.markers.includes(hoveredLayer)" in full
    assert "findOfficialMarkerRecordByElement" not in full
    assert "closest('.leaflet-marker-icon')" not in full


def test_official_route_marker_association_refreshes_hover_after_leaflet_and_rechecks_click():
    full = FULL_SCRIPT.read_text(encoding="utf-8")

    assert "container.addEventListener('pointermove', STATE._routeMarkerPointerMoveHandler, true)" in full
    assert "requestAnimationFrame(() =>" in full
    assert "STATE._routeMarkerHoveredRecord = findOfficialMarkerHitByCanvas(event.target)" in full
    assert "const markerRecord = findOfficialMarkerHitByCanvas(event.target);" in full
    assert "STATE._routeMarkerHoveredRecord" not in full.split(
        "const markerRecord = findOfficialMarkerHitByCanvas(event.target);", 1
    )[1].split("if (!markerRecord) return;", 1)[0]


def test_official_marker_visibility_accepts_pinia_proxy_of_captured_leaflet_map():
    full = FULL_SCRIPT.read_text(encoding="utf-8")

    assert "function getLeafletMapContainer(map)" in full
    assert "function isSameLeafletMap(candidate, expected)" in full
    assert "const storeMap = getMapStore()?.mapInstance || null;" in full
    assert "isSameLeafletMap(marker._map, storeMap)" in full
    assert "isSameLeafletMap(marker._map, capturedMap)" in full
    assert "candidateContainer === expectedContainer" in full
    assert "if (marker._map && (!map || marker._map === map)) return true;" not in full


def test_route_marker_display_defaults_to_highlight_without_saved_preference():
    full = FULL_SCRIPT.read_text(encoding="utf-8")

    assert "return ['none', 'highlight', 'focus'].includes(value) ? value : 'highlight';" in full


def test_non_preview_editing_restores_unrelated_markers_and_keeps_association_circles():
    full = FULL_SCRIPT.read_text(encoding="utf-8")

    branch = "if (editingRoute && !editingRoute.graphPreviewMode) {"
    assert branch in full
    branch_body = full.split(branch, 1)[1].split("}", 1)[0]
    assert "clearMarkerFocus('route');" in branch_body
    assert "highlightRouteAssociatedMarkers(getRouteAssociatedMarkers(editingRoute));" in branch_body
    assert "clearRouteMarkerHighlights();" not in branch_body
    assert "return;" in branch_body

    selecting_index = full.index("if (selectingMarkers) {")
    restore_index = full.index(branch)
    mode_index = full.index("const mode = STATE.routeManager.markerDisplayMode;", restore_index)
    assert selecting_index < restore_index < mode_index


def test_route_editor_can_switch_between_popup_insert_and_continuous_drawing():
    for text in scripts():
        assert "createNewRoute: null" in text
        assert "function createEmptyRouteGraph(routeName)" in text
        assert "STATE.routeManager.createNewRoute = function()" in text
        assert "rawData: createEmptyRouteGraph(name)" in text
        assert "this.startEdit(route.id);" in text
        assert "id=\"sm-create-route-btn\"" in text
        assert "$('#sm-create-route-btn').onclick = () => STATE.routeManager.createNewRoute();" in text
        assert 'id="kmp-toolbar-draw-mode">连续绘制</button>' in text
        assert "route.continuousDrawMode = !!route.isNewRoute;" in text
        assert "setExclusiveGraphEditMode(activeRoute, 'draw', !activeRoute.continuousDrawMode);" in text
        assert "route.continuousDrawLastNodeId = null;" in text
        assert "route.continuousDrawMode && route.continuousDrawLastNodeId" in text
        assert "graph.edges.push({ id: nextGraphEdgeId(graph), from: previousNode.id, to: node.id });" in text
        assert "if (route.continuousDrawMode) route.continuousDrawLastNodeId = node.id;" in text
        assert "panel.innerText = '连续绘制模式\\n右键地图：连续添加并连接路线点\\n再次点击“连续绘制”可切回弹窗插入';" in text
        assert "if (route.continuousDrawMode) {" in text
        assert "if (route.isNewRoute) {" not in text
        assert "createBtn.disabled = editing;" in text


def test_rendering_uses_graph_edges_in_both_scripts():
    for text in scripts():
        assert "function drawGraphOnLayer(layerGroup, graph, options = {})" in text
        assert "drawGraphOnLayer(layerGroup, normalizeRouteGraph(data))" in text
        assert "graph.edges.forEach(edge =>" in text
        assert "const fromNode = nodeById.get(edge.from)" in text
        assert "const toNode = nodeById.get(edge.to)" in text


def test_regular_editing_hides_saved_arrows_but_preview_keeps_them_in_both_scripts():
    for text in scripts():
        assert "const showDirectionArrows = options.showDirectionArrows !== false;" in text
        assert "if (showDirectionArrows) {" in text
        assert "showDirectionArrows: !!route.graphPreviewMode" in text
        assert "drawEditDirectionArrow(group, latLngs[0], latLngs[1], { selected });" in text


def test_saved_and_preview_arrows_follow_directed_chains_and_interpolate_inside_edges():
    for text in scripts():
        assert "function buildDirectedGraphChains(graph)" in text
        assert "function getGraphChainArrowPlacements(chain, nodeById, arrowGap)" in text
        assert "const inDegree = new Map();" in text
        assert "const outDegree = new Map();" in text
        assert "inDegree.get(currentNodeId) === 1" in text
        assert "outDegree.get(currentNodeId) === 1" in text
        assert "const arrowCount = Math.max(1, Math.floor(totalLength / gap));" in text
        assert "const x = segment.fromNode.x + (segment.toNode.x - segment.fromNode.x) * t;" in text
        assert "const y = segment.fromNode.y + (segment.toNode.y - segment.fromNode.y) * t;" in text
        assert "const chains = buildDirectedGraphChains(graph);" in text
        assert "getGraphChainArrowPlacements(chain, nodeById, SETTINGS.arrowGap)" in text
        assert "L.marker(arrowLatLng" in text
        assert "L.marker(endLatLng" not in text
        assert "let cumulativeDist = 0;" not in text


def test_editing_uses_graph_not_editing_points_in_both_scripts():
    for text in scripts():
        assert "route.editingGraph = deepCloneJson(normalizeRouteGraph(route.rawData, route.name))" in text
        assert "route._editSnapshotStr = JSON.stringify(route.editingGraph)" in text
        assert "route.editingPoints =" not in text
        assert "getRouteSegmentsFromRawData" not in text


def test_graph_edit_actions_exist_in_both_scripts():
    for text in scripts():
        assert "function openEdgeEditPopup(route, edge, latlng)" in text
        assert "function openGraphNodeEditPopup(route, node, latlng, nodeSize)" in text
        assert "function insertNodeOnEdge(route, edge, latlng)" in text
        assert "function deleteGraphNode(route, nodeId)" in text
        assert "function deleteGraphEdge(route, edgeId)" in text
        assert "function connectGraphNodes(route, fromNodeId, toNodeId)" in text


def test_child_route_model_is_not_present_in_both_scripts():
    for text in scripts():
        assert "childrenRoutes" not in text
        assert "ROUTE_CHILD_MAX_DEPTH" not in text
        assert "createChildRouteFromNode" not in text
        assert "deleteWholeChildRoute" not in text


def test_graph_selection_and_context_menu_helpers_exist_in_both_scripts():
    for text in scripts():
        assert "function ensureGraphSelectionState(route)" in text
        assert "function toggleGraphSelection(route, type, id)" in text
        assert "function selectSingleGraphElement(route, type, id)" in text
        assert "function clearGraphSelection(route)" in text
        assert "function openGraphContextMenu(route, type, id, latlng)" in text
        assert "function openGraphMultiSelectPopup(route, latlng)" in text
        assert "hitPolyline.on('contextmenu'" in text
        assert "marker.on('contextmenu'" in text


def test_graph_direction_and_delete_operations_exist_in_both_scripts():
    for text in scripts():
        assert "function reverseGraphEdge(route, edgeId)" in text
        assert "function reverseSelectedGraphEdges(route)" in text
        assert "function deleteSelectedGraphEdges(route)" in text
        assert "function deleteSelectedGraphNodes(route)" in text
        assert "function deleteAdjacentGraphNode(route, edgeId, side)" in text
        assert "deleteGraphEdge(route, edgeId)" in text
        assert "deleteGraphNode(route, nodeId)" in text


def test_editing_visual_feedback_helpers_exist_in_both_scripts():
    for text in scripts():
        assert "function drawEditDirectionArrow(group, fromLatLng, toLatLng, state)" in text
        assert "function createEditConnectionPreview(route)" in text
        assert "function updateEditConnectionPreview(route, latlng)" in text
        assert "function updateGraphEditToolbar(route)" in text
        assert "function updateGraphEditHelpPanel(route)" in text
        assert "kmp-graph-edit-toolbar" in text
        assert "kmp-graph-edit-help" in text


def test_editing_direction_arrow_normalizes_leaflet_latlng_arrays_in_both_scripts():
    for text in scripts():
        assert "const from = L.latLng(fromLatLng)" in text
        assert "const to = L.latLng(toLatLng)" in text
        assert "const midLat = (from.lat + to.lat) / 2" in text
        assert "const midLng = (from.lng + to.lng) / 2" in text


def test_editing_direction_arrow_reuses_saved_route_fishtail_shape_in_both_scripts():
    for text in scripts():
        assert "function createRouteDirectionArrowHtml(angle, sizePx, options = {})" in text
        assert 'd="M 0 0 L 10 5 L 0 10 L 3 5 Z"' in text
        assert "createRouteDirectionArrowHtml(angle, sizePx" in text
        assert ".kmp-route-arrow svg" in text
        assert "border-left: 8px solid" not in text
        assert "border-top: 5px solid transparent" not in text
        assert "border-bottom: 5px solid transparent" not in text


def test_editing_blank_map_click_clears_selection_and_connect_mode_in_both_scripts():
    for text in scripts():
        assert "function isGraphEditBackgroundEvent(e)" in text
        assert "clearGraphSelection(route);" in text
        assert "removeEditConnectionPreview(route);" in text


def test_editing_connection_click_is_not_broken_by_target_hover_redraw_in_both_scripts():
    for text in scripts():
        assert "if (route.pendingConnectFromNodeId) {" in text
        assert "connectGraphNodes(route, route.pendingConnectFromNodeId, node.id)" in text
        assert "marker.on('mouseover'" not in text
        assert "marker.on('mouseout'" not in text


def test_editing_background_context_menu_can_insert_standalone_node_in_both_scripts():
    for text in scripts():
        assert "function addGraphNodeAtLatLng(route, latlng)" in text
        assert "function openGraphBackgroundEditPopup(route, latlng)" in text
        assert "btn-add-standalone-node" in text
        assert "addGraphNodeAtLatLng(route, latlng)" in text
        assert "openGraphBackgroundContextMenu(route, e.latlng)" in text


def test_editing_continuous_selection_treats_shift_like_drag_in_both_scripts():
    for text in scripts():
        assert "e.originalEvent && (e.originalEvent.shiftKey || route.continuousSelectionMode)" in text
        assert "route._graphBrushSelectionStarted" in text
        assert "route._graphBrushSelectionMoved" in text


def test_editing_box_selection_mode_disables_map_drag_and_highlights_toolbar_in_both_scripts():
    for text in scripts():
        assert "map.dragging.disable()" in text
        assert "map.dragging.enable()" in text
        assert "setExclusiveGraphEditMode(route, `box-${mode}`, route.graphBoxSelectMode !== mode)" in text
        assert "boxNodeBtn.classList.toggle('active'" in text
        assert "boxEdgeBtn.classList.toggle('active'" in text


def test_graph_edit_toolbar_modes_are_mutually_exclusive_in_both_scripts():
    for text in scripts():
        assert "function setExclusiveGraphEditMode(route, mode, enabled = true)" in text
        assert "const activeMode = enabled ? mode : null;" in text
        assert "route.continuousDrawMode = activeMode === 'draw';" in text
        assert "route.continuousSelectionMode = activeMode === 'selection';" in text
        assert "route.graphBoxSelectMode = activeMode === 'box-node'" in text
        assert "route.graphPreviewMode = activeMode === 'preview';" in text
        assert "syncGraphBoxSelectionMapDrag(route);" in text
        assert "setExclusiveGraphEditMode(activeRoute, 'selection', !activeRoute.continuousSelectionMode);" in text
        assert "setExclusiveGraphEditMode(activeRoute, 'preview', !!previewInput.checked);" in text
        assert "activeRoute.continuousDrawMode = !activeRoute.continuousDrawMode;" not in text
        assert "activeRoute.continuousSelectionMode = !activeRoute.continuousSelectionMode;" not in text
        assert "activeRoute.graphPreviewMode = !!previewInput.checked;" not in text

    full = FULL_SCRIPT.read_text(encoding="utf-8")
    lite = LITE_SCRIPT.read_text(encoding="utf-8")
    assert "route.markerAssociationMode = activeMode === 'markers';" in full
    assert "setExclusiveGraphEditMode(route, 'markers', enabled);" in full
    assert "route.markerAssociationMode = activeMode === 'markers';" not in lite


def test_special_marker_group_operations_execute_in_both_scripts():
    for script_path in (FULL_SCRIPT, LITE_SCRIPT):
        operations = run_graph_data_harness(script_path)["groupOperations"]

        assert operations["firstCreatedGroupId"] == "smg2"
        assert operations["repeatedCreatedGroupId"] == "smg2"
        assert operations["nextCreatedGroupId"] == "smg4"
        assert operations["invalidAddResults"] == [False, False, False]
        assert operations["invalidAddsUnchanged"] is True
        assert operations["movedBetweenGroups"] is True
        assert operations["afterMoveBetweenGroups"][0]["node_ids"] == ["n1", "n2", "n3"]
        assert operations["afterMoveBetweenGroups"][1]["node_ids"] == []
        assert operations["duplicateAdd"] is False
        assert operations["removedMember"] is True
        assert operations["removedMissingMember"] is False
        assert operations["movedUp"] is True
        assert operations["movePastTop"] is False
        assert operations["movedDown"] is True
        assert operations["movePastBottom"] is False
        assert operations["deletedGroup"] is True
        assert operations["deletedMissingGroup"] is False
        assert [group["id"] for group in operations["remainingGroups"]] == [
            "smg3",
            "empty",
            "smg2",
        ]
        assert operations["remainingGroups"][0]["node_ids"] == []
        assert operations["beforeDeleteNodeIds"] == operations["afterDeleteNodeIds"]


def test_special_marker_group_mode_is_top_level_and_clears_adding_state_in_both_scripts():
    for script_path in (FULL_SCRIPT, LITE_SCRIPT):
        result = run_graph_data_harness(script_path)["modeOperations"]
        after_enter = result["afterEnterGroupMode"]
        after_switch = result["afterSwitchMode"]
        after_exit = result["afterExitMode"]

        assert after_enter["specialMarkerGroupMode"] is True
        assert after_enter["specialMarkerAddingGroupId"] is None
        assert after_enter["pendingConnectFromNodeId"] is None
        assert after_enter["connectionPreview"] is None
        assert after_enter["graphSelectionType"] is None
        assert after_enter["graphSelectedIds"] == []
        assert after_switch["specialMarkerGroupMode"] is False
        assert after_switch["specialMarkerAddingGroupId"] is None
        assert after_switch["specialMarkerSelectedGroupId"] is None
        assert after_switch["continuousSelectionMode"] is True
        assert after_exit["specialMarkerGroupMode"] is False
        assert after_exit["specialMarkerAddingGroupId"] is None
        assert after_exit["specialMarkerSelectedGroupId"] is None
        assert after_exit["continuousSelectionMode"] is False
        assert result["removedPreviewCount"] == 1
        assert result["refreshCount"] == 3


def test_special_marker_group_editor_interaction_contract_is_symmetric_without_official_leakage():
    for text in scripts():
        assert "const SPECIAL_MARKER_GROUP_TEXT =" in text
        assert 'id="kmp-toolbar-special-groups"' in text
        assert "SPECIAL_MARKER_GROUP_TEXT.toolbar" in text
        assert "setExclusiveGraphEditMode(activeRoute, 'special-groups', !activeRoute.specialMarkerGroupMode);" in text
        assert text.count("route.specialMarkerGroupMode = false;") >= 3
        assert text.count("route.specialMarkerAddingGroupId = null;") >= 4
        assert text.count("route.specialMarkerSelectedGroupId = null;") >= 3
        assert ".kmp-edit-node-coordinate" in text
        assert "interactive: !route.isBoxSelecting && !route.graphPreviewMode && !route.specialMarkerGroupMode" in text
        assert "if (route.graphPreviewMode) return;\n            if (route.specialMarkerGroupMode) {" in text
        assert "addNodeToSpecialMarkerGroup(route, route.specialMarkerAddingGroupId, node.id)" in text
        assert "if (route.specialMarkerGroupMode) return;\n            if (route.pendingConnectFromNodeId)" in text
        assert "draggable: !route.isBoxSelecting && !route.specialMarkerGroupMode" in text
        assert "if (route.graphPreviewMode || route.specialMarkerGroupMode) return;" in text
        assert "function openGraphBackgroundContextMenu(route, latlng) {\n        if (route.specialMarkerGroupMode) return;" in text
        assert "if (route.specialMarkerGroupMode) {\n                L.DomEvent.preventDefault(e);" in text
        assert "if (route.specialMarkerAddingGroupId) {" in text
        assert "route.specialMarkerAddingGroupId = null;\n                refreshGraphEditRoute(route);\n                return;" in text
        assert "if (activeRoute.specialMarkerGroupMode) {\n            panel.style.display = 'none';\n            return;\n        }" in text
        assert "const normalSelectionActionsEnabled = !activeRoute.specialMarkerGroupMode && count > 0;" in text
        assert "status.style.display = activeRoute.specialMarkerGroupMode ? 'none' : '';" in text
        assert "if (activeRoute.specialMarkerGroupMode) return;\n                reverseSelectedGraphEdges(activeRoute);" in text
        assert "if (activeRoute.specialMarkerGroupMode) return;\n                if (activeRoute.graphSelectionType === 'edge')" in text
        assert "if (activeRoute.specialMarkerGroupMode) return;\n                clearGraphSelection(activeRoute);" in text

    full = FULL_SCRIPT.read_text(encoding="utf-8")
    lite = LITE_SCRIPT.read_text(encoding="utf-8")
    assert 'id="kmp-toolbar-route-markers"' in full
    assert 'id="kmp-toolbar-route-markers"' not in lite


def test_special_marker_group_mode_coordinate_label_executes_in_both_scripts():
    for script_path in (FULL_SCRIPT, LITE_SCRIPT):
        result = run_graph_data_harness(script_path)["editNodeIcons"]
        assert '<div class="kmp-edit-node-coordinate">11, 20</div>' in result["grouped"]
        assert "kmp-edit-node-coordinate" not in result["regular"]


def test_special_marker_color_conversion_and_style_restore_execute_in_both_scripts():
    for script_path in (FULL_SCRIPT, LITE_SCRIPT):
        result = run_graph_data_harness(script_path)

        assert [sample["roundTrip"] for sample in result["colorSamples"]] == [
            sample["hex"] for sample in result["colorSamples"]
        ]
        assert result["invalidHex"] is None
        assert result["normalizedRgbHex"] == "#FF0010"
        assert result["styleDraft"]["restored"] is True
        assert result["styleDraft"]["current"] == result["styleDraft"]["snapshot"]
        assert result["styleDraft"]["detached"] is True


def test_route_arrow_spacing_uses_compact_default_and_range_in_both_scripts():
    for text in scripts():
        assert "defaultWeight: 4, defaultSize: 1.2, defaultGap: 150" in text
        assert 'id="rng-g" min="10" max="500" step="10"' in text
        assert 'id="rng-g" min="100" max="2000" step="100"' not in text


def test_route_list_removes_legacy_box_delete_but_keeps_save_and_cancel():
    for text in scripts():
        assert '<button class="box-select"' not in text
        assert "querySelector('.box-select')" not in text
        assert '<button class="save"' in text
        assert '<button class="cancel"' in text


def test_graph_edit_toolbar_has_separate_save_cancel_action_group_in_both_scripts():
    for text in scripts():
        assert 'class="kmp-toolbar-commit-group"' in text
        assert 'id="kmp-toolbar-save">保存</button>' in text
        assert 'id="kmp-toolbar-cancel">取消</button>' in text
        assert ".kmp-toolbar-commit-group" in text
        assert "border-left: 2px solid" in text
        assert "STATE.routeManager.saveEdit(activeRoute.id)" in text
        assert "STATE.routeManager.cancelEdit(activeRoute.id)" in text


def test_ctrl_right_drag_suppresses_the_following_context_menu_in_both_scripts():
    for text in scripts():
        assert "if (route._graphSuppressNextContextMenu || ev.ctrlKey)" in text
        assert "if (ev.button === 2) route._graphSuppressNextContextMenu = true;" in text
        assert "L.DomEvent.preventDefault(e);" in text
        assert "L.DomEvent.stopPropagation(e);" in text
        assert "setTimeout(() => { route._graphSuppressNextContextMenu = false; }, 250);" in text


def test_editing_clear_selection_button_uses_unambiguous_label_in_both_scripts():
    for text in scripts():
        assert '<button type="button" id="kmp-toolbar-clear">取消选中</button>' in text
        assert '<button type="button" id="kmp-toolbar-clear">清除</button>' not in text
        assert "Esc：取消选中" in text
        assert "Esc：清除选择" not in text


def test_route_and_edit_panes_stay_below_leaflet_popup_pane_in_both_scripts():
    for text in scripts():
        assert "KMP_ARROW_PANE_Z_INDEX = 650" in text
        assert "KMP_EDIT_LINE_PANE_Z_INDEX = 660" in text
        assert "KMP_EDIT_MARKER_PANE_Z_INDEX = 670" in text
        assert "KMP_EDIT_DECORATION_PANE_Z_INDEX = 680" in text
        assert "arrowPane.style.zIndex = KMP_ARROW_PANE_Z_INDEX" in text
        assert "style.zIndex = KMP_EDIT_LINE_PANE_Z_INDEX" in text
        assert "style.zIndex = KMP_EDIT_MARKER_PANE_Z_INDEX" in text
        assert "style.zIndex = KMP_EDIT_DECORATION_PANE_Z_INDEX" in text
        assert "style.pointerEvents = 'none'" in text
        assert "style.zIndex = 9001" not in text
        assert "style.zIndex = 9002" not in text
        assert "p.style.zIndex = 800" not in text


def test_special_marker_group_contract_replaces_legacy_node_style_rendering():
    for text in scripts():
        assert "const SPECIAL_MARKER_SHAPES = [" in text
        assert "const DEFAULT_SPECIAL_MARKER_STYLE =" in text
        assert "function normalizeRouteCoordinate(value)" in text
        assert "function normalizeHexColor(value, fallback)" in text
        assert "function clampNumber(value, min, max, fallback)" in text
        assert "function normalizeSpecialMarkerStyle(style)" in text
        assert "function normalizeSpecialMarkerGroups(rawData, nodeIds)" in text
        assert "function normalizeGraphNodeStyle(node)" not in text
        assert "function formatGraphNodeLabel(index, labelStyle)" not in text
        assert "function getGraphNodeStyleGroupKey(style)" not in text
        assert "function getGraphNodeStyleSequenceMap(graph)" not in text
        assert "...normalizeGraphNodeStyle(node)" not in text
        assert "function createGraphNodeStyleHtml(node, index)" not in text
        assert "function renderGraphNodeStyleMarkers(layerGroup, graph)" not in text
        assert "function renderSpecialMarkerGroups(layerGroup, graph, options = {})" in text
        assert "renderSpecialMarkerGroups(layerGroup, graph, { pane: 'kmp-edit-decoration-pane' })" in text
        for shape in (
            "circle",
            "square",
            "rounded-square",
            "diamond",
            "triangle-up",
            "triangle-down",
            "pentagon",
            "hexagon",
            "octagon",
            "star",
            "ellipse",
            "capsule",
        ):
            assert f".kmp-special-marker-shape.{shape}" in text
        assert "function removeNodeFromSpecialMarkerGroups(graph, nodeId)" in text
        assert "removeNodeFromSpecialMarkerGroups(graph, nodeId);" in text
        assert "kmp-node-edit-popup" in text
        assert "kmp-node-edit-actions" in text
        assert "NODE_LABEL_STYLE_OPTIONS" not in text
        assert "NODE_MARKER_STYLE_OPTIONS" not in text
        assert "NODE_COLOR_OPTIONS" not in text
        assert "kmp-node-style-grid" not in text
        assert "kmp-node-style-option" not in text
        assert "graphNodeStyleOptionHtml" not in text
        assert "createGraphNodeStyleGridHtml" not in text
        assert "bindGraphNodeStyleOptions" not in text
        assert "保存Z</button>" in text
        assert "开始连接</button>" in text
        assert "删除点</button>" in text


def test_special_marker_group_sidebar_modal_and_color_picker_contract_is_symmetric():
    for text in scripts():
        assert "function updateSpecialMarkerGroupSidebar(route)" in text
        assert "sidebar.id = 'kmp-special-marker-sidebar'" in text
        assert "function openSpecialMarkerStyleModal(route, groupId = null)" in text
        assert "modal.id = 'kmp-special-marker-style-modal'" in text
        assert "function createSpecialMarkerColorPicker(container, initialColor, onChange)" in text
        assert "kmp-color-sv" in text
        assert "kmp-color-hue" in text
        assert "-webkit-appearance: none" in text
        assert "appearance: none" in text
        assert ".kmp-color-hue::-webkit-slider-runnable-track" in text
        assert ".kmp-color-hue::-webkit-slider-thumb" in text
        assert "background: linear-gradient(to right, #f00, #ff0, #0f0, #0ff, #00f, #f0f, #f00)" in text
        assert "kmp-color-hex" in text
        assert "SPECIAL_MARKER_SHAPES.map" in text
        assert "SPECIAL_MARKER_GROUP_TEXT.groupLabel" in text
        assert "SPECIAL_MARKER_GROUP_TEXT.createGroup" in text
        assert "SPECIAL_MARKER_GROUP_TEXT.addNode" in text
        assert "SPECIAL_MARKER_GROUP_TEXT.editStyle" in text
        assert "SPECIAL_MARKER_GROUP_TEXT.deleteGroup" in text
        assert "SPECIAL_MARKER_GROUP_TEXT.removeMember" in text
        assert "SPECIAL_MARKER_GROUP_TEXT.cancel" in text
        assert "SPECIAL_MARKER_GROUP_TEXT.create" in text
        assert "SPECIAL_MARKER_GROUP_TEXT.done" in text
        assert "sidebar.dataset.eventsBound" in text
        assert "closeSpecialMarkerStyleModal(route, false)" in text

        sidebar_start = text.index("    function updateSpecialMarkerGroupSidebar(route) {")
        sidebar_end = text.index("    function deleteGraphNode(route, nodeId) {", sidebar_start)
        sidebar_block = text[sidebar_start:sidebar_end]
        assert "const escapedGroupId = escapeHtml(String(group.id));" in sidebar_block
        assert "const escapedNodeId = escapeHtml(String(nodeId));" in sidebar_block
        assert 'data-group-id="${escapedGroupId}"' in sidebar_block
        assert 'data-node-id="${escapedNodeId}"' in sidebar_block
        assert 'data-group-id="${group.id}"' not in sidebar_block
        assert 'data-node-id="${nodeId}"' not in sidebar_block


def test_removing_an_editing_route_cleans_special_marker_ui_in_both_scripts():
    for text in scripts():
        start = text.index("    STATE.routeManager.remove = function(id) {")
        end = text.index("    STATE.routeManager.toggleVisible = function(id) {", start)
        remove_block = text[start:end]

        assert "closeSpecialMarkerStyleModal(r, false);" in remove_block
        assert "r.specialMarkerGroupMode = false;" in remove_block
        assert "r.specialMarkerAddingGroupId = null;" in remove_block
        assert "r.specialMarkerSelectedGroupId = null;" in remove_block
        assert "updateSpecialMarkerGroupSidebar(null);" in remove_block


def test_bulk_clear_routes_cleans_special_marker_ui_in_both_scripts():
    for text in scripts():
        start = text.index("        $('#sm-clear-route').onclick = () => {")
        end = text.index("        const bindSlider = (id, key, valId) => {", start)
        clear_block = text[start:end]

        assert "closeSpecialMarkerStyleModal(r, false);" in clear_block
        assert "r.specialMarkerGroupMode = false;" in clear_block
        assert "r.specialMarkerAddingGroupId = null;" in clear_block
        assert "r.specialMarkerSelectedGroupId = null;" in clear_block
        assert "updateSpecialMarkerGroupSidebar(null);" in clear_block


def test_special_marker_groups_and_legacy_conversion_execute_in_both_scripts():
    for script_path in (FULL_SCRIPT, LITE_SCRIPT):
        result = run_graph_data_harness(script_path)

        assert result["shapes"] == [
            "circle",
            "square",
            "rounded-square",
            "diamond",
            "triangle-up",
            "triangle-down",
            "pentagon",
            "hexagon",
            "octagon",
            "star",
            "ellipse",
            "capsule",
        ]

        v2 = result["v2"]
        assert [set(node) for node in v2["nodes"]] == [
            {"id", "x", "y", "z"},
            {"id", "x", "y", "z"},
            {"id", "x", "y", "z"},
        ]
        assert v2["nodes"] == [
            {"id": "n1", "x": 11, "y": 20, "z": -2},
            {"id": "n2", "x": 30, "y": 41, "z": 2},
            {"id": "n3", "x": 50, "y": 60, "z": 3},
        ]
        assert v2["special_marker_groups"][0]["node_ids"] == ["n2", "n1"]
        assert v2["special_marker_groups"][1]["node_ids"] == ["n3"]
        assert v2["special_marker_groups"][2]["node_ids"] == []
        assert v2["special_marker_groups"][0]["style"] == {
            "shape": "star",
            "fill_color": "#ABCDEF",
            "number": {
                "font_size": 30,
                "color": "#010203",
                "outline": {"enabled": False, "width": 3, "color": "#AABBCC"},
            },
        }
        assert result["withoutGroups"]["special_marker_groups"] == []
        assert result["serialized"]["special_marker_groups"] == v2["special_marker_groups"]
        assert result["empty"]["special_marker_groups"] == []

        consecutive = result["consecutive"]
        assert consecutive["special_marker_groups"] == []
        assert [(node["x"], node["y"], node["z"]) for node in consecutive["nodes"]] == [
            (0, 0, 0),
            (10, 10, 2),
            (20, 20, 3),
        ]
        assert consecutive["edges"] == [
            {"id": "e1", "from": "n1", "to": "n2"},
            {"id": "e2", "from": "n2", "to": "n3"},
        ]
        node_by_id = {node["id"]: node for node in consecutive["nodes"]}
        assert all(
            (node_by_id[edge["from"]]["x"], node_by_id[edge["from"]]["y"])
            != (node_by_id[edge["to"]]["x"], node_by_id[edge["to"]]["y"])
            for edge in consecutive["edges"]
        )

        segmented = result["segmented"]
        assert [(edge["from"], edge["to"]) for edge in segmented["edges"]] == [
            ("n1", "n2"),
            ("n3", "n4"),
        ]
        assert len({(node["x"], node["y"]) for node in segmented["nodes"]}) == 4

        assert all(
            isinstance(node[axis], int)
            for graph in (v2, consecutive, result["revisited"], segmented)
            for node in graph["nodes"]
            for axis in ("x", "y", "z")
        )

        assert [call["latlng"] for call in result["renderCalls"]] == [
            [30, 41],
            [11, 20],
            [50, 60],
        ]
        assert [">1<" in call["html"] for call in result["renderCalls"]] == [True, False, True]
        assert ">2<" in result["renderCalls"][1]["html"]
        assert "--node-color:#ABCDEF" in result["renderCalls"][0]["html"]
        assert "font-size:30px" in result["renderCalls"][0]["html"]
        assert "color:#010203" in result["renderCalls"][0]["html"]
        assert "-webkit-text-stroke" not in result["renderCalls"][0]["html"]
        assert "-webkit-text-stroke:2px #111111" in result["renderCalls"][2]["html"]
        expected_shapes = ["diamond", "star", "triangle-up", "circle"]
        assert len(result["shapeRenderCalls"]) == len(expected_shapes)
        for shape, call in zip(expected_shapes, result["shapeRenderCalls"], strict=True):
            assert f'class="kmp-route-node-core kmp-special-marker-shape {shape}"' in call["html"]
        assert result["afterDeleteGroups"][0]["node_ids"] == ["n2"]


def test_legacy_nonconsecutive_duplicate_moves_one_unit_and_preserves_connections():
    for script_path in (FULL_SCRIPT, LITE_SCRIPT):
        revisited = run_graph_data_harness(script_path)["revisited"]
        assert [(node["x"], node["y"]) for node in revisited["nodes"]] == [
            (100, 200),
            (120, 220),
            (101, 200),
        ]
        assert [(edge["from"], edge["to"]) for edge in revisited["edges"]] == [
            ("n1", "n2"),
            ("n2", "n3"),
        ]


def test_legacy_duplicate_relocation_is_bounded_to_one_unit_neighbors():
    for text in scripts():
        assert "const neighborOffsets = [" in text
        assert "const availableOffset = neighborOffsets.find" in text
        assert "if (!availableOffset) return;" in text
        assert "for (let distance = 1" not in text


def test_graph_coordinate_edit_assignments_are_integer_normalized_in_both_scripts():
    for text in scripts():
        assert "x: normalizeRouteCoordinate(gamePos.x)" in text
        assert "y: normalizeRouteCoordinate(gamePos.y)" in text
        assert "z: normalizeRouteCoordinate(fromNode.z)" in text
        assert "node.x = normalizeRouteCoordinate(newGamePos.x);" in text
        assert "node.y = normalizeRouteCoordinate(newGamePos.y);" in text
        assert "node.z = normalizeRouteCoordinate(zInput.value);" in text


def test_editing_intercepts_map_defaults_in_both_scripts():
    for text in scripts():
        assert "function installGraphEditInputInterceptors()" in text
        assert "disableGraphEditMapDefaults(route)" in text
        assert "enableGraphEditMapDefaults(route)" in text
        assert "keydown', handleGraphEditKeydown, true" in text
        assert "contextmenu', handleGraphEditContextMenu, true" in text
        assert "if (e.key === 'Tab')" in text
        assert "if (e.key === 'Escape')" in text
        assert "function handleGraphEditContextMenu(e)" in text


def test_graph_drag_and_box_selection_helpers_exist_in_both_scripts():
    for text in scripts():
        assert "GRAPH_BOX_SELECT_THRESHOLD_RATIO = 0.5" in text
        assert "function startGraphBrushSelection(route, type, id)" in text
        assert "function updateGraphBrushSelection(route, latlng)" in text
        assert "function finishGraphBrushSelection(route)" in text
        assert "function startGraphBoxSelection(route, type, latlng, additive)" in text
        assert "function finishGraphBoxSelection(route)" in text
        assert "function selectGraphElementsInBounds(route, type, bounds, additive)" in text
