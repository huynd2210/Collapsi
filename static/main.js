let state = null;
let aiSide = null;
let humanSide = null;
let legalMoves = [];
let gameOver = false;
let winnerSide = null;

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

// Auto-start
newGame();


