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
      const key = `${r},${c}`;
      if (collapsed.has(key)) {
        cell.className = 'cell collapsed';
        cell.textContent = '·';
      } else if (p1r === r && p1c === c) {
        cell.className = 'cell p1';
        cell.textContent = 'X';
      } else if (p2r === r && p2c === c) {
        cell.className = 'cell p2';
        cell.textContent = 'O';
      } else {
        cell.textContent = grid[idx];
      }
      const isLegal = legalMoves.some(([rr, cc]) => rr === r && cc === c);
      if (!gameOver && isLegal && state.turn === humanSide) {
        cell.classList.add('hint');
      }
      if (!gameOver && state.turn === humanSide && isLegal) {
        cell.classList.add('clickable');
        cell.addEventListener('click', () => onClickMove(r, c));
      }
      elBoard.appendChild(cell);
    }
  }
  const base = `Turn: Player ${playerSymbol(state.turn)} — AI: ${playerSymbol(aiSide)} — You: ${playerSymbol(humanSide)}`;
  elInfo.textContent = gameOver ? `${base} — Winner: Player ${playerSymbol(winnerSide)}` : base;
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

// Auto-start
newGame();


