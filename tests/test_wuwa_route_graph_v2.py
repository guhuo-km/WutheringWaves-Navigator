from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FULL_SCRIPT = PROJECT_ROOT / "js" / "wuwa_map_optimizer.js"
LITE_SCRIPT = PROJECT_ROOT / "js" / "wuwa_map_optimizer_lite.js"


def scripts() -> list[str]:
    return [
        FULL_SCRIPT.read_text(encoding="utf-8"),
        LITE_SCRIPT.read_text(encoding="utf-8"),
    ]


def test_graph_constants_and_helpers_exist_in_both_scripts():
    for text in scripts():
        assert "ROUTE_GRAPH_SCHEMA = 'wuwa-route-graph'" in text
        assert "ROUTE_GRAPH_VERSION = 2" in text
        assert "function makeGraphNodeId(index)" in text
        assert "function makeGraphEdgeId(index)" in text
        assert "function normalizeRouteGraph(rawData, routeName = 'route')" in text
        assert "function normalizeLegacyRouteGraph(rawData, routeName)" in text
        assert "function serializeRouteGraph(route)" in text


def test_rendering_uses_graph_edges_in_both_scripts():
    for text in scripts():
        assert "function drawGraphOnLayer(layerGroup, graph)" in text
        assert "drawGraphOnLayer(layerGroup, normalizeRouteGraph(data))" in text
        assert "graph.edges.forEach(edge =>" in text
        assert "const fromNode = nodeById.get(edge.from)" in text
        assert "const toNode = nodeById.get(edge.to)" in text


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
        assert "route.graphBoxSelectMode = route.graphBoxSelectMode === mode ? null : mode" in text
        assert "boxNodeBtn.classList.toggle('active'" in text
        assert "boxEdgeBtn.classList.toggle('active'" in text


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
        assert "arrowPane.style.zIndex = KMP_ARROW_PANE_Z_INDEX" in text
        assert "style.zIndex = KMP_EDIT_LINE_PANE_Z_INDEX" in text
        assert "style.zIndex = KMP_EDIT_MARKER_PANE_Z_INDEX" in text
        assert "style.zIndex = 9001" not in text
        assert "style.zIndex = 9002" not in text
        assert "p.style.zIndex = 800" not in text


def test_node_style_popup_and_render_helpers_exist_in_both_scripts():
    for text in scripts():
        assert "NODE_LABEL_STYLE_OPTIONS = ['none', 'badge', 'dot', 'alpha']" in text
        assert "NODE_MARKER_STYLE_OPTIONS = ['none', 'diamond', 'star', 'triangle']" in text
        assert "NODE_COLOR_OPTIONS = [" in text
        assert "function normalizeGraphNodeStyle(node)" in text
        assert "...normalizeGraphNodeStyle(node)" in text
        assert "function formatGraphNodeLabel(index, labelStyle)" in text
        assert "if (labelStyle === 'badge') return String(n)" in text
        assert "if (labelStyle === 'dot') return `${n}.`" in text
        assert "if (labelStyle === 'alpha') return `A${n}`" in text
        assert "function getGraphNodeStyleGroupKey(style)" in text
        assert "function getGraphNodeStyleSequenceMap(graph)" in text
        assert "const key = getGraphNodeStyleGroupKey(style)" in text
        assert "counts.set(key, sequence)" in text
        assert "const sequenceMap = getGraphNodeStyleSequenceMap(graph)" in text
        assert "sequenceMap.get(node.id)" in text
        assert "function createGraphNodeStyleHtml(node, index)" in text
        assert "if (style.markerStyle === 'none') return ''" in text
        assert "kmp-route-node-core" in text
        assert "kmp-route-node-text" in text
        assert 'class="kmp-route-node-shape ${style.markerStyle}"' not in text
        assert "kmp-route-node-label" not in text
        assert "function renderGraphNodeStyleMarkers(layerGroup, graph)" in text
        assert "renderGraphNodeStyleMarkers(layerGroup, graph)" in text
        assert "kmp-node-edit-popup" in text
        assert "kmp-node-edit-actions" in text
        assert "kmp-node-style-grid" in text
        assert "kmp-node-style-option" in text
        assert 'data-node-style-field="${field}"' in text
        assert "graphNodeStyleOptionHtml('labelStyle', 'badge', '①'" in text
        assert "graphNodeStyleOptionHtml('labelStyle', 'dot', '1.'" in text
        assert "graphNodeStyleOptionHtml('labelStyle', 'alpha', 'A'" in text
        assert "graphNodeStyleOptionHtml('markerStyle', 'diamond', '◇'" in text
        assert "graphNodeStyleOptionHtml('markerStyle', 'star', '☆'" in text
        assert "graphNodeStyleOptionHtml('markerStyle', 'triangle', '△'" in text
        assert "graphNodeStyleOptionHtml('color', color" in text
        assert "bindGraphNodeStyleOptions(route, node)" in text
        assert "保存Z</button>" in text
        assert "开始连接</button>" in text
        assert "删除点</button>" in text


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
