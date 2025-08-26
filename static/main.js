let state = null;
let aiSide = null;
let humanSide = null;
let legalMoves = [];
let gameOver = false;
let winnerSide = null;
// History tree: nodes { id, parentId|null, state, move|null, children:[] }
let history = [];
let currentNodeId = null;
// Linear stack for undo/redo on the most recent line
let linearStack = [];
let linearIndex = -1; // points at current node index in linearStack
let editMode = false;
let suggestedMove = null;
let editorError = '';
let placing = null; // reserved (not used in simplified editor)
let editorXs = new Set();
let editorOs = new Set();

const elBoard = document.getElementById('board');
const elInfo = document.getElementById('info');
const elSize = document.getElementById('size');
const elSeed = document.getElementById('seed');

document.getElementById('newGame').addEventListener('click', async () => {
  await newGame();
});

document.getElementById('aiMove').addEventListener('click', async () => {
  if (!state) return;
  await aiMove();
});
document.getElementById('undo').addEventListener('click', () => doUndo());
document.getElementById('redo').addEventListener('click', () => doRedo());
document.getElementById('editToggle').addEventListener('click', () => toggleEdit());
document.getElementById('solve').addEventListener('click', () => doSolve());
// Editor-only controls are shown in UI as the single Solve button when in edit mode

async function newGame() {
  const size = elSize.value;
  const seed = elSeed.value ? Number(elSeed.value) : null;
  const resp = await fetch('/api/new', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ size, seed }),
  });
  const data = await resp.json();
  if (!data.ok) return;
  state = data.state;
  aiSide = data.state.aiSide;
  humanSide = data.state.humanSide;
  legalMoves = data.legalMoves;
  gameOver = false;
  winnerSide = null;
  suggestedMove = null;
  // reset history tree
  history = [];
  const rootId = genId();
  history.push({ id: rootId, parentId: null, state: deepClone(state), move: null, children: [] });
  currentNodeId = rootId;
  linearStack = [rootId];
  linearIndex = 0;
  render();
  await maybeAutoAI();
}

function render() {
  if (!state) return;
  const width = state.board.width;
  const height = state.board.height;
  const grid = state.board.grid;
  const collapsed = new Set(state.collapsed.map(([r, c]) => `${r},${c}`));
  const [p1r, p1c] = state.p1;
  const [p2r, p2c] = state.p2;
  elBoard.style.gridTemplateColumns = `repeat(${width}, 64px)`;
  elBoard.innerHTML = '';
  for (let r = 0; r < height; r++) {
    for (let c = 0; c < width; c++) {
      const idx = r * width + c;
      const cell = document.createElement('div');
      cell.className = 'cell card';
      const token = getCellToken(r, c, collapsed);
      if (token === '·') {
        cell.className = 'cell collapsed';
        cell.textContent = '·';
      } else if (token === 'X') {
        cell.className = 'cell p1';
        cell.textContent = 'X';
        const badge = document.createElement('div');
        badge.className = 'cell-num';
        const val = state.board.grid[idx];
        badge.textContent = String(val);
        cell.appendChild(badge);
      } else if (token === 'O') {
        cell.className = 'cell p2';
        cell.textContent = 'O';
        const badge = document.createElement('div');
        badge.className = 'cell-num';
        const val = state.board.grid[idx];
        badge.textContent = String(val);
        cell.appendChild(badge);
      } else {
        cell.textContent = token;
      }
      const isLegal = legalMoves.some(([rr, cc]) => rr === r && cc === c);
      if (editMode) {
        cell.classList.add('clickable');
        cell.addEventListener('click', () => onEditCell(r, c));
        cell.addEventListener('contextmenu', (e) => { e.preventDefault(); onRightClickCell(r, c); });
      } else {
        if (!gameOver && isLegal && state.turn === humanSide) {
          cell.classList.add('hint');
        }
        if (!gameOver && state.turn === humanSide && isLegal) {
          cell.classList.add('clickable');
          cell.addEventListener('click', () => onClickMove(r, c));
        }
        if (suggestedMove && suggestedMove[0] === r && suggestedMove[1] === c) {
          cell.classList.add('suggested');
        }
      }
      elBoard.appendChild(cell);
    }
  }
  const base = `Turn: Player ${playerSymbol(state.turn)} — AI: ${playerSymbol(aiSide)} — You: ${playerSymbol(humanSide)}`;
  const mode = editMode ? ' — Edit mode' : '';
  const err = editorError ? ` — Error: ${editorError}` : '';
  elInfo.textContent = gameOver ? `${base}${mode}${err} — Winner: Player ${playerSymbol(winnerSide)}` : `${base}${mode}${err}`;
  renderHistory();
}

async function onClickMove(r, c) {
  const resp = await fetch('/api/move', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ state, move: [r, c] }),
  });
  const data = await resp.json();
  if (!data.ok) {
    alert(data.error || 'Illegal move');
    return;
  }
  state = data.state;
  legalMoves = data.legalMoves;
  const over = checkGameOver();
  // Add new node branching from current
  const node = findNode(currentNodeId);
  const dedupId = findExistingChildByState(node, state);
  if (dedupId) {
    currentNodeId = dedupId;
  } else {
    const newId = genId();
    const child = { id: newId, parentId: node.id, state: deepClone(state), move: [r, c], children: [] };
    node.children.push(newId);
    history.push(child);
    currentNodeId = newId;
  }
  // update linear stack: truncate forward and push current
  linearStack = linearStack.slice(0, linearIndex + 1);
  linearStack.push(currentNodeId);
  linearIndex = linearStack.length - 1;
  render();
  // If AI turn after human, trigger AI (if not game over)
  if (!over && state.turn === aiSide) {
    await aiMove();
  }
}

async function aiMove() {
  const resp = await fetch('/api/ai', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ state }),
  });
  const data = await resp.json();
  if (!data.ok) return;
  state = data.state;
  legalMoves = data.legalMoves;
  if (data.winner) {
    gameOver = true;
    winnerSide = data.winner;
  } else {
    checkGameOver();
  }
  // Add AI move to history as a child from current (dedup by resulting state)
  const node = findNode(currentNodeId);
  const dedupId = findExistingChildByState(node, state);
  if (dedupId) {
    currentNodeId = dedupId;
  } else {
    const newId = genId();
    const child = { id: newId, parentId: node.id, state: deepClone(state), move: data.move || null, children: [] };
    node.children.push(newId);
    history.push(child);
    currentNodeId = newId;
  }
  // update linear stack for AI move as well
  linearStack = linearStack.slice(0, linearIndex + 1);
  linearStack.push(currentNodeId);
  linearIndex = linearStack.length - 1;
  render();
}

function playerSymbol(player) {
  return player === 1 ? 'X' : 'O';
}

async function maybeAutoAI() {
  // If AI starts or it's AI's turn for any reason, make the move automatically
  if (state && state.turn === aiSide) {
    // slight delay to let UI paint
    await new Promise((r) => setTimeout(r, 50));
    await aiMove();
  }
}

function checkGameOver() {
  if (legalMoves && legalMoves.length === 0) {
    // current player cannot move; other player wins
    gameOver = true;
    winnerSide = state.turn === 1 ? 2 : 1;
    return true;
  }
  return false;
}

function renderHistory() {
  const el = document.getElementById('history');
  el.innerHTML = '';
  const title = document.createElement('h2');
  title.textContent = 'Move History';
  el.appendChild(title);
  if (!history.length) return;
  // Build plies array from current branch back to root
  const line = linearizeToRoot(currentNodeId).reverse();
  // Render in two columns: X and O moves per row
  const table = document.createElement('table');
  table.className = 'moves-table';
  const thead = document.createElement('thead');
  thead.innerHTML = '<tr><th class="ply">#</th><th>X</th><th>O</th></tr>';
  table.appendChild(thead);
  const tbody = document.createElement('tbody');
  for (let i = 1; i < line.length; i++) { // skip root (start)
    const node = line[i];
    const plyIndex = i - 1; // 0-based move index
    const isX = plyIndex % 2 === 0;
    if (isX) {
      const tr = document.createElement('tr');
      const tdNum = document.createElement('td');
      tdNum.className = 'ply';
      tdNum.textContent = String((plyIndex / 2) + 1);
      const tdX = document.createElement('td');
      const tdO = document.createElement('td');
      tdX.className = 'move' + (node.id === currentNodeId ? ' current' : '');
      tdX.textContent = node.move ? `(${node.move[0]},${node.move[1]})` : '';
      tdX.addEventListener('click', () => gotoNode(node.id));
      tr.appendChild(tdNum);
      tr.appendChild(tdX);
      tr.appendChild(tdO);
      tbody.appendChild(tr);
    } else {
      // fill O column on the last row
      const lastTr = tbody.lastElementChild;
      const tdO = lastTr.children[2];
      tdO.className = 'move' + (node.id === currentNodeId ? ' current' : '');
      tdO.textContent = node.move ? `(${node.move[0]},${node.move[1]})` : '';
      tdO.addEventListener('click', () => gotoNode(node.id));
    }
  }
  table.appendChild(tbody);
  el.appendChild(table);
  // Replace the old tree UI with compact branching chips per ply row
  const branches = buildBranches(line);
  const rows = tbody.querySelectorAll('tr');
  branches.forEach((chips, i) => {
    const row = rows[i];
    if (!row) return;
    const chipBar = document.createElement('div');
    chipBar.className = 'branch-chips';
    chips.forEach((node) => {
      const chip = document.createElement('div');
      chip.className = 'chip' + (node.id === currentNodeId ? ' current' : '');
      chip.textContent = node.move ? `(${node.move[0]},${node.move[1]})` : 'start';
      chip.title = 'Jump to branch';
      chip.addEventListener('click', () => gotoNode(node.id));
      chipBar.appendChild(chip);
    });
    const td = document.createElement('td');
    td.colSpan = 2;
    td.appendChild(chipBar);
    const branchRow = document.createElement('tr');
    branchRow.appendChild(td);
    tbody.appendChild(branchRow);
  });
}

// Old tree UI removed. The branching is shown via chips attached to the table.

function gotoNode(id) {
  const node = findNode(id);
  state = deepClone(node.state);
  currentNodeId = id;
  // When navigating, refresh legal moves via server to respect game rules
  fetch('/api/legal', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ state }),
  })
    .then((r) => r.json())
    .then((data) => {
      if (data.ok) {
        legalMoves = data.legalMoves;
        gameOver = legalMoves.length === 0;
        winnerSide = gameOver ? (state.turn === 1 ? 2 : 1) : null;
        render();
      }
    });
}

function findNode(id) {
  return history.find((n) => n.id === id);
}

function nodeDepth(node) {
  let d = 0;
  let cur = node;
  while (cur.parentId !== null) {
    cur = findNode(cur.parentId);
    d++;
  }
  return d;
}

function genId() {
  return Math.random().toString(36).slice(2, 10);
}

function deepClone(obj) {
  return JSON.parse(JSON.stringify(obj));
}

function linearizeToRoot(id) {
  const nodes = [];
  let cur = findNode(id);
  while (cur) {
    nodes.push(cur);
    if (cur.parentId === null) break;
    cur = findNode(cur.parentId);
  }
  return nodes;
}

// For each ply index, return all nodes in history that are at that ply depth,
// and that share the same ancestor chain up to previous ply in the current line.
function buildBranches(line) {
  // line is root..current
  const root = line[0];
  // Precompute depths
  const depthMap = new Map();
  history.forEach((n) => depthMap.set(n.id, nodeDepth(n)));
  // Build ancestor chain for lookup
  const idSet = new Set(line.map((n) => n.id));
  const branches = [];
  for (let i = 1; i < line.length; i++) {
    const expectedDepth = i;
    const parent = line[i - 1];
    let siblings = history.filter((n) => depthMap.get(n.id) === expectedDepth && n.parentId === parent.id);
    // Deduplicate by resulting state key
    const seen = new Set();
    siblings = siblings.filter((n) => {
      const k = stateKey(n.state);
      if (seen.has(k)) return false;
      seen.add(k);
      return true;
    });
    branches.push(siblings);
  }
  return branches;
}

function findExistingChildByState(parentNode, childState) {
  for (const childId of parentNode.children) {
    const child = findNode(childId);
    if (stateKey(child.state) === stateKey(childState)) {
      return child.id;
    }
  }
  return null;
}

function stateKey(s) {
  const b = s.board;
  const gridStr = (b.grid || []).join('');
  const p1 = `${s.p1[0]},${s.p1[1]}`;
  const p2 = `${s.p2[0]},${s.p2[1]}`;
  const collapsed = (s.collapsed || [])
    .map(([r, c]) => `${r},${c}`)
    .sort()
    .join(';');
  return `${b.width}x${b.height}|${gridStr}|${p1}|${p2}|${collapsed}|${s.turn}`;
}

function doUndo() {
  if (linearIndex <= 0) return;
  linearIndex -= 1;
  const id = linearStack[linearIndex];
  gotoNodeKeepLine(id);
}

function doRedo() {
  if (linearIndex + 1 >= linearStack.length) return;
  linearIndex += 1;
  const id = linearStack[linearIndex];
  gotoNodeKeepLine(id);
}

function gotoNodeKeepLine(id) {
  const node = findNode(id);
  state = deepClone(node.state);
  currentNodeId = id;
  suggestedMove = null;
  fetch('/api/legal', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ state }),
  })
    .then((r) => r.json())
    .then((data) => {
      if (data.ok) {
        legalMoves = data.legalMoves;
        gameOver = legalMoves.length === 0;
        winnerSide = gameOver ? (state.turn === 1 ? 2 : 1) : null;
        render();
      }
    });
}

function toggleEdit() {
  editMode = !editMode;
  suggestedMove = null;
  editorError = '';
  if (editMode) {
    // Empty-looking board: keep grid valid (A) but collapse all cells so they render as '.'
    const w = state.board.width;
    const h = state.board.height;
    state.board.grid = Array.from({ length: w * h }, () => 'A');
    state.collapsed = [];
    for (let r = 0; r < h; r++) {
      for (let c = 0; c < w; c++) {
        state.collapsed.push([r, c]);
      }
    }
    state.p1 = [-1, -1];
    state.p2 = [-1, -1];
    editorXs = new Set();
    editorOs = new Set();
    state.turn = 1;
    placing = null;
  }
  const solveBtn = document.getElementById('solve');
  if (solveBtn) solveBtn.style.display = editMode ? '' : 'none';
  render();
}

function onEditCell(r, c) {
  const idx = r * state.board.width + c;
  const key = `${r},${c}`;
  const collapsedSet = new Set(state.collapsed.map(([rr, cc]) => `${rr},${cc}`));
  const current = getCellToken(r, c, collapsedSet);
  const order = ['·', 'A', '2', '3', '4', 'X', 'O'];
  const next = order[(order.indexOf(current) + 1) % order.length];
  if (next === '·') {
    if (!collapsedSet.has(key)) state.collapsed.push([r, c]);
    editorXs.delete(key);
    editorOs.delete(key);
  } else if (next === 'X') {
    editorXs.add(key);
    editorOs.delete(key);
    state.collapsed = state.collapsed.filter(([rr, cc]) => !(rr === r && cc === c));
  } else if (next === 'O') {
    editorOs.add(key);
    editorXs.delete(key);
    state.collapsed = state.collapsed.filter(([rr, cc]) => !(rr === r && cc === c));
  } else {
    state.board.grid[idx] = next;
    state.collapsed = state.collapsed.filter(([rr, cc]) => !(rr === r && cc === c));
    editorXs.delete(key);
    editorOs.delete(key);
  }
  refreshLegal();
}

function refreshLegal() {
  // Only compute legal moves if both players placed
  if (!state || state.p1[0] < 0 || state.p1[1] < 0 || state.p2[0] < 0 || state.p2[1] < 0) {
    render();
    return;
  }
  fetch('/api/legal', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ state }),
  })
    .then((r) => r.json())
    .then((data) => {
      if (data.ok) {
        legalMoves = data.legalMoves;
        render();
      }
    });
}

function onRightClickCell(r, c) {
  // Right-click collapses to '.'
  const key = `${r},${c}`;
  const collapsedSet = new Set(state.collapsed.map(([rr, cc]) => `${rr},${cc}`));
  if (!collapsedSet.has(key)) state.collapsed.push([r, c]);
  editorXs.delete(key);
  editorOs.delete(key);
  refreshLegal();
}

function getCellToken(r, c, collapsedSet) {
  const key = `${r},${c}`;
  if (editMode) {
    if (editorXs.has(key)) return 'X';
    if (editorOs.has(key)) return 'O';
  } else {
    if (state.p1[0] === r && state.p1[1] === c) return 'X';
    if (state.p2[0] === r && state.p2[1] === c) return 'O';
  }
  if (collapsedSet.has(key)) return '·';
  return state.board.grid[r * state.board.width + c];
}

function doSolve() {
  suggestedMove = null;
  // validate exactly one X and one O placed
  // from editor overlays
  const xCount = editorXs.size;
  const oCount = editorOs.size;
  if (xCount !== 1 || oCount !== 1) {
    editorError = 'Place exactly one X and one O before solving';
    render();
    return;
  }
  // commit overlays into state positions
  const [xr, xc] = Array.from(editorXs)[0].split(',').map(Number);
  const [or, oc] = Array.from(editorOs)[0].split(',').map(Number);
  state.p1 = [xr, xc];
  state.p2 = [or, oc];
  editorError = '';
  fetch('/api/solve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ state }),
  })
    .then((r) => r.json())
    .then((data) => {
      if (data.ok) {
        // Exit editor mode and return to play with the edited board
        editMode = false;
        suggestedMove = null;
        editorXs = new Set();
        editorOs = new Set();
        const solveBtn = document.getElementById('solve');
        if (solveBtn) solveBtn.style.display = 'none';
        // Ensure AI is the winning side for the edited position
        if (data.win === true) {
          aiSide = state.turn;
          humanSide = state.turn === 1 ? 2 : 1;
        } else {
          aiSide = state.turn === 1 ? 2 : 1;
          humanSide = state.turn;
        }
        // Refresh legal moves for the committed X/O positions
        fetch('/api/legal', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ state }),
        })
          .then((r2) => r2.json())
          .then((d2) => {
            if (d2.ok) {
              legalMoves = d2.legalMoves;
              gameOver = legalMoves.length === 0;
            }
            // Reset history and linear stack to the edited position as a new game root
            history = [];
            const rootId = genId();
            history.push({ id: rootId, parentId: null, state: deepClone(state), move: null, children: [] });
            currentNodeId = rootId;
            linearStack = [rootId];
            linearIndex = 0;
            render();
            // If it's AI's turn, make the first move automatically
            if (aiSide === state.turn && !gameOver) {
              setTimeout(() => { aiMove(); }, 50);
            }
          });
      }
    });
}

function setPlacing(which) {
  if (!editMode) return;
  placing = which;
}

function clearPiece(which) {
  if (!editMode) return;
  if (which === 'X') state.p1 = [-1, -1];
  if (which === 'O') state.p2 = [-1, -1];
  refreshLegal();
}

// Auto-start
newGame();


