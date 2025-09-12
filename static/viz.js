(() => {
  const elStatus = document.getElementById('status');
  const elStats = document.getElementById('statsPanel');
  const elCards = document.getElementById('cards');
  const elDb = document.getElementById('dbPath');
  const elIdx = document.getElementById('indexPath');
  const elN2R = document.getElementById('norm2rawDir');
  const elPrev = document.getElementById('prevPage');
  const elNext = document.getElementById('nextPage');
  const elPrev2 = document.getElementById('prevPage2');
  const elNext2 = document.getElementById('nextPage2');
  const elPageInfo = document.getElementById('pageInfo');
  const elPageInfo2 = document.getElementById('pageInfo2');
  const elRefreshStats = document.getElementById('refreshStats');
 
  let offset = 0;
  const limit = 50;
  let pollTimer = null;

  function setStatus(msg) {
    if (elStatus) elStatus.textContent = msg || '';
  }

  function fmtRate(x) {
    if (x == null || isNaN(x)) return '—';
    return (x * 100).toFixed(2) + '%';
  }

  async function fetchJSON(url, body) {
    const resp = await fetch(url, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(body || {}),
    });
    const data = await resp.json();
    return data;
  }
 
  async function pollIndexUntilReady(db, indexPath) {
    if (pollTimer) return;
    pollTimer = setInterval(async () => {
      try {
        const st = await fetchJSON('/api/index/status', { db, index: indexPath });
        const recs = st && st.index && typeof st.index.records === 'number' ? st.index.records : null;
        if (recs && recs > 0) {
          clearInterval(pollTimer);
          pollTimer = null;
          if (!elIdx.value && indexPath) elIdx.value = indexPath;
          setStatus('Index ready');
          // reload to render overlays
          loadPage();
        } else {
          setStatus('Building index...');
        }
      } catch (e) {
        // keep polling quietly
      }
    }, 2000);
  }
 
  async function refreshStats() {
    try {
      setStatus('Loading stats...');
      const data = await fetchJSON('/api/solved/stats', {
        db: elDb.value || undefined,
        limit: 0, // all
      });
      if (!data || !data.ok) {
        // If server suggests a DB path, prefill and retry once
        if (data && data.suggestedDb) {
          const prev = elDb.value;
          if (!prev || prev !== data.suggestedDb) {
            elDb.value = data.suggestedDb;
            setStatus('Using suggested DB...');
            // retry stats load with suggested path
            return refreshStats();
          }
        }
        const sugg = (data && Array.isArray(data.suggestedPaths) && data.suggestedPaths.length) ? ` (suggested: ${data.suggestedPaths[0]})` : '';
        elStats.innerHTML = `<div class="muted">Stats error: ${data?.error || 'unknown'}${sugg}</div>`;
        setStatus('Stats error');
        return;
      }
      const s = data;

      // Prefer new keys if available; fall back to legacy "winRate"
      const mX = (s.moverWinRate && s.moverWinRate.X != null) ? s.moverWinRate.X : (s.winRate && s.winRate.X != null ? s.winRate.X : null);
      const mO = (s.moverWinRate && s.moverWinRate.O != null) ? s.moverWinRate.O : (s.winRate && s.winRate.O != null ? s.winRate.O : null);

      // Overall share from server if present
      let shX = (s.overallWinShare && s.overallWinShare.X != null) ? s.overallWinShare.X : null;
      let shO = (s.overallWinShare && s.overallWinShare.O != null) ? s.overallWinShare.O : null;

      // Fallback #1: derive from winnerCounts if provided by server
      if ((shX == null || isNaN(shX)) && s.winnerCounts) {
        const wcX = Number(s.winnerCounts.X ?? 0);
        const wcO = Number(s.winnerCounts.O ?? 0);
        const denom = wcX + wcO;
        if (denom > 0) {
          const shareX = Math.min(1, Math.max(0, wcX / denom));
          shX = shareX;
          shO = 1 - shareX;
        }
      }

      // Fallback #2: derive overall share from winsByTurn and turns (robust to missing/zero total)
      if ((shX == null || isNaN(shX)) && s.winsByTurn && s.turns) {
        const xWins = Number(s.winsByTurn.X ?? 0);
        const oWins = Number(s.winsByTurn.O ?? 0);
        const tX = Number(s.turns.X ?? 0);
        const tO = Number(s.turns.O ?? 0);
        const totalRaw = (typeof s.total === 'number') ? Number(s.total) : NaN;
        const total = (isNaN(totalRaw) || totalRaw <= 0) ? (tX + tO) : totalRaw;
        if (total > 0) {
          // X overall wins = (X-to-move positions that are wins for mover) + (O-to-move positions that are losses for mover)
          const xOverallWins = xWins + Math.max(0, tO - oWins);
          const shareX = Math.min(1, Math.max(0, xOverallWins / total));
          shX = shareX;
          shO = 1 - shareX;
        }
      }

      elStats.innerHTML = `
        <div><b>Total records:</b> ${s.total}</div>
        <div><b>Turns:</b> X=${s.turns.X} O=${s.turns.O}</div>
        <div><b>Wins (all):</b> win=${s.wins.win} loss=${s.wins.loss}</div>
        <div><b>Mover win rate (conditional on side to move):</b> X=${fmtRate(mX)} O=${fmtRate(mO)}</div>
        <div><b>Overall win share (should sum ≈ 100%):</b> X=${fmtRate(shX)} O=${fmtRate(shO)}</div>
        ${ s.winnerCounts ? `<div><b>Overall winner counts:</b> X=${Number(s.winnerCounts.X||0)} O=${Number(s.winnerCounts.O||0)}</div>` : '' }
        <div class="muted">Mover rate looks only at positions where that side is to move. Overall win share looks across all records.</div>
        <div><b>Plies:</b> min=${s.plies.min ?? '—'} avg=${s.plies.avg != null ? s.plies.avg.toFixed(2) : '—'} max=${s.plies.max ?? '—'}</div>
      `;
      setStatus('');
    } catch (e) {
      elStats.innerHTML = `<div class="muted">Stats error</div>`;
      setStatus('Stats error');
    }
  }

  function renderMiniBoard(container, state, options) {
    // state from server state_to_json
    // options: {cell: 18 (px)}
    const size = (options && options.cell) || 22;
    container.innerHTML = '';
    container.className = 'mini-board';
    container.style.gridTemplateColumns = `repeat(${state.board.width}, ${size}px)`;
    const collapsedSet = new Set((state.collapsed || []).map(([r,c]) => `${r},${c}`));
    const [p1r, p1c] = state.p1 || [null, null];
    const [p2r, p2c] = state.p2 || [null, null];
    for (let r = 0; r < state.board.height; r++) {
      for (let c = 0; c < state.board.width; c++) {
        const idx = r * state.board.width + c;
        const cell = document.createElement('div');
        cell.className = 'mini-cell';
        if (p1r === r && p1c === c) {
          cell.classList.add('mini-p1');
          cell.textContent = 'X';
        } else if (p2r === r && p2c === c) {
          cell.classList.add('mini-p2');
          cell.textContent = 'O';
        } else if (collapsedSet.has(`${r},${c}`)) {
          cell.classList.add('mini-collapsed');
          cell.textContent = '·';
        } else {
          cell.textContent = String(state.board.grid[idx] || '');
        }
        container.appendChild(cell);
      }
    }
  }

  function cardHeader(entry) {
    const mover = entry.turn === 0 ? 'X' : 'O';
    const outcome = entry.win ? 'win' : 'loss';
    const plies = entry.plies != null ? entry.plies : '—';
    return `Key ${entry.keyHex}|${entry.turn} — mover ${mover} — ${outcome} in ${plies}`;
  }

  async function loadPage() {
    try {
      setStatus('Loading page...');
      const priorIndex = (elIdx.value || '').trim();
      const body = {
        db: elDb.value || undefined,
        index: priorIndex || undefined,
        offset,
        limit,
      };
      const data = await fetchJSON('/api/solved/page', body);
      if (!data || !data.ok) {
        // If server suggests a DB path, prefill and retry once
        if (data && data.suggestedDb) {
          const prev = elDb.value;
          if (!prev || prev !== data.suggestedDb) {
            elDb.value = data.suggestedDb;
            setStatus('Using suggested DB...');
            return loadPage();
          }
        }
        const sugg = (data && Array.isArray(data.suggestedPaths) && data.suggestedPaths.length) ? ` (suggested: ${data.suggestedPaths[0]})` : '';
        elCards.innerHTML = `<div class="muted">Load error: ${data?.error || 'unknown'}${sugg}</div>`;
        setStatus('Page error');
        return;
      }
      // Adopt server-suggested index path if provided
      if (data.indexPath && priorIndex !== data.indexPath) {
        elIdx.value = data.indexPath;
        setStatus('Index auto-detected');
      }
      // Kick off/poll index build whenever the server indicates a build
      if (data.indexBuild) {
        if (data.indexBuild.error) {
          setStatus('Index builder error: ' + data.indexBuild.error);
        } else if (data.indexBuild.started) {
          setStatus('Building index in background...');
          const idxPath = data.indexPath || elIdx.value || 'data/norm_index.db';
          pollIndexUntilReady(elDb.value || undefined, idxPath);
        }
      }
      const items = data.items || [];
      elCards.innerHTML = '';
      items.forEach((entry, idx) => {
        const card = document.createElement('div');
        card.className = 'viz-card';
        const header = document.createElement('div');
        header.textContent = cardHeader(entry);
        header.className = 'viz-card-title';
        card.appendChild(header);

        const mini = document.createElement('div');
        mini.style.marginTop = '4px';
        if (entry.state) {
          renderMiniBoard(mini, entry.state, {cell: 22});
        } else {
          mini.innerHTML = '<span class="muted">no overlay (index missing). Set Index above or place norm_index.db under data/</span>';
        }
        card.appendChild(mini);

        const meta = document.createElement('div');
        meta.className = 'meta';
        meta.textContent = `best=${entry.best} key=${entry.keyHex}|${entry.turn}`;
        card.appendChild(meta);

        const actions = document.createElement('div');
        actions.className = 'viz-actions';
        const btnExpand = document.createElement('button');
        btnExpand.className = 'btn btn-outline btn-sm';
        btnExpand.textContent = 'Expand';
        const btnPlayNorm = document.createElement('button');
        btnPlayNorm.className = 'btn btn-primary btn-sm';
        btnPlayNorm.textContent = 'Play normalized';
        btnPlayNorm.disabled = !entry.state;
        actions.appendChild(btnExpand);
        actions.appendChild(btnPlayNorm);
        card.appendChild(actions);

        const variantsWrap = document.createElement('div');
        variantsWrap.className = 'viz-variants';
        variantsWrap.style.display = 'none';
        variantsWrap.innerHTML = '<div class="muted">Loading variants...</div>';
        card.appendChild(variantsWrap);

        btnPlayNorm.addEventListener('click', () => {
          if (!entry.state) return;
          try {
            localStorage.setItem('collapsi.playState', JSON.stringify(entry.state));
          } catch {}
          window.location.href = '/';
        });

        btnExpand.addEventListener('click', async () => {
          if (variantsWrap.style.display === 'none') {
            variantsWrap.style.display = '';
            variantsWrap.innerHTML = '<div class="muted">Loading variants...</div>';
            try {
              const vdata = await fetchJSON('/api/solved/raw_variants', {
                keyHex: entry.keyHex,
                turn: entry.turn,
                index: elIdx.value || undefined,
                norm2rawDir: elN2R.value || undefined,
              });
              if (!vdata || !vdata.ok) {
                variantsWrap.innerHTML = `<div class="muted">Variants error: ${vdata?.error || 'unknown'}</div>`;
                return;
              }
              const list = vdata.variants || [];
              if (!list.length) {
                variantsWrap.innerHTML = `<div class="muted">No raw variants found (check norm2raw and index)</div>`;
                return;
              }
              const grid = document.createElement('div');
              grid.className = 'variants-grid';
              list.forEach((it) => {
                const vcard = document.createElement('div');
                vcard.className = 'variant-card';
                const vhead = document.createElement('div');
                vhead.textContent = `raw ${it.rawKey} shift (dr=${it.dr}, dc=${it.dc})`;
                vhead.style.fontSize = '12px';
                vhead.style.marginBottom = '4px';
                vcard.appendChild(vhead);
                const vmini = document.createElement('div');
                renderMiniBoard(vmini, it.state, {cell: 18});
                vcard.appendChild(vmini);
                const vact = document.createElement('div');
                vact.className = 'viz-actions';
                const btnPlay = document.createElement('button');
                btnPlay.className = 'btn btn-primary btn-sm';
                btnPlay.textContent = 'Play';
                btnPlay.addEventListener('click', () => {
                  try {
                    localStorage.setItem('collapsi.playState', JSON.stringify(it.state));
                  } catch {}
                  window.location.href = '/';
                });
                vact.appendChild(btnPlay);
                vcard.appendChild(vact);
                grid.appendChild(vcard);
              });
              variantsWrap.innerHTML = '';
              variantsWrap.appendChild(grid);
            } catch (e) {
              variantsWrap.innerHTML = `<div class="muted">Variants error</div>`;
            }
          } else {
            variantsWrap.style.display = 'none';
          }
        });

        elCards.appendChild(card);
      });

      const pageText = `offset ${offset}, showing ${items.length} (limit ${limit})`;
      if (elPageInfo) elPageInfo.textContent = pageText;
      if (elPageInfo2) elPageInfo2.textContent = pageText;

      setStatus('');
    } catch (e) {
      elCards.innerHTML = `<div class="muted">Load error</div>`;
      setStatus('Page error');
    }
  }

  function bindNav() {
    function prev() {
      offset = Math.max(0, offset - limit);
      loadPage();
    }
    function next() {
      offset += limit;
      loadPage();
    }
    if (elPrev) elPrev.addEventListener('click', prev);
    if (elPrev2) elPrev2.addEventListener('click', prev);
    if (elNext) elNext.addEventListener('click', next);
    if (elNext2) elNext2.addEventListener('click', next);
    if (elRefreshStats) elRefreshStats.addEventListener('click', () => {
      refreshStats();
    });
  }

  // init
  bindNav();
  refreshStats().then(() => loadPage());
})();