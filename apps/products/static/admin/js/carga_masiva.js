/**
 * Carga masiva por expansión — admin de Productos → Carga de stock.
 *
 * Elegís la expansión en la barra de arriba (la misma de la carga individual)
 * y el set entero cae en una tabla editable. Un GET trae todo; filtros, orden,
 * pestañas y páginas corren en el cliente; un POST guarda. Es la de Delta Old
 * adaptada a Crack (apps/products/set_load).
 *
 * Piezas:
 *   store    estado único (filas + filtros) y las reglas puras sobre él
 *   table    dibuja la página actual (100 filas) y actualiza filas sueltas
 *   keys     navegación por teclado entre filas y columnas
 *   groups   grupos de precio ("Grupo 1 = USD 30")
 *   adv      opciones avanzadas de una fila (diálogo)
 *   review   revisión antes de subir
 *   api      set y guardado (idempotente por request_id)
 *
 * Cada fila tiene su `uid`: una misma carta puede estar varias veces (otro
 * acabado, idioma o condición) con el botón de duplicar.
 *
 * Se habla con el resto de la pantalla por eventos del documento:
 *   cl:before-set-change (cancelable) y cl:set-change.
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const wrap = document.querySelector(".cl-wrap");
  const root = $("cm");
  if (!wrap || !root) return;

  const CFG = JSON.parse($("cm-config").textContent);
  const jsonOf = (id, fallback) => { const el = $(id); return el ? JSON.parse(el.textContent) : fallback; };
  const CONDITIONS = jsonOf("cm-conditions", []);
  const CONDITION_SHORT = Object.fromEntries(CONDITIONS.map((c) => [String(c.id), c.short]));
  // Acabados de TCGplayer ("Reverse Holofoil") y cómo se leen ("Reverse Holo").
  const FINISHES = jsonOf("cm-finish-labels", {});
  const finishLabel = (a) => FINISHES[a] || a;
  // Insignias de los acabados alternativos (R = Reverse Holo, 1st = 1st Edition…).
  // Un acabado que no tenga una definida usa una gris con su inicial.
  const CHIPS = jsonOf("cm-finish-badges", []);
  const chipOf = (printing) => CHIPS.find((c) => c.printings.includes(printing)) ||
    { key: printing, short: printing.charAt(0).toUpperCase(), label: finishLabel(printing), color: "#64748b", printings: [printing] };
  // Particularidades de la unidad (alterada, firmada...): casilla sí/no en
  // toda carta suelta. Cada una con su ícono y su color, como los acabados.
  const ATTRS = jsonOf("cm-attributes", []);
  // Idiomas que se eligen por fila. Japonés no: un set japonés ya es japonés
  // (su imagen es otra), así que ahí el idioma va fijo.
  const LANGUAGES = jsonOf("cm-languages", []);
  const LANGUAGE_INFO = jsonOf("cm-language-flags", {});
  const flagImg = (code, cls = "cm-flag") => (LANGUAGE_INFO[code]
    ? `<img class="${cls}" src="${esc(LANGUAGE_INFO[code].flag)}" alt="" title="${esc(LANGUAGE_INFO[code].label)}">` : "");
  const isJapaneseSet = () => !!S.set && S.set.language === "ja";
  const attrColor = (a) => a.color || "#334155";
  // Las columnas fijas, en el orden de TCG Fans: R · alterada · firmada ·
  // estampada · recién abierta · 1st. Están en todos los sets (la casilla de
  // R o 1st aparece solo en las cartas sueltas).
  const FIXED_CHIPS = ["reverse", "1st"];
  const chipByKey = (k) => CHIPS.find((c) => c.key === k);
  /**
   * La impresión que marca la casilla de una insignia en esa carta: la del
   * catálogo si la tiene; si no, y es R o 1st, igual se ofrece (TCGplayer no
   * siempre publica esas variantes; mismo criterio que finishes.OPTIONAL).
   * La 1st de una carta holo es "1st Edition Holofoil".
   */
  function printingFor(card, c) {
    const own = card.printings || [];
    const alt = own.slice(1).find((a) => c.printings.includes(a));
    if (alt || !card.is_card || !FIXED_CHIPS.includes(c.key)) return alt || null;
    if (c.printings.includes(own[0])) return null;   // ya es la impresión por defecto
    if (c.key === "reverse") return "Reverse Holofoil";
    return /Holofoil/.test(own[0] || "") ? "1st Edition Holofoil" : "1st Edition";
  }
  // La insignia: el ícono si tiene, si no la letra en su color.
  const badgeHtml = (c, color) => c.icon
    ? `<img class="cm-badge" src="${esc(c.icon)}" alt="${esc(c.short)}" title="${esc(c.label)}">`
    : `<span class="cm-chip" style="--c:${color}" title="${esc(c.label)}">${esc(c.short)}</span>`;
  const noAttrs = () => Object.fromEntries(ATTRS.map((a) => [a.field, false]));
  const attrsOn = (r) => ATTRS.filter((a) => r.attrs[a.field]);
  // Los acabados de una carta que se marcan con checkbox: todos menos el por defecto.
  const altFinishes = (card) => (card.is_card ? (card.printings || []).slice(1) : []);

  const PAGE_SIZE = 100;
  const FIELDS = ["idioma", "cond", "qty", "price"];
  const MODE_KEY = "crack.cargaStock.modo";

  // ------------------------------------------------------------- utilidades
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
    (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
  const money = (n) => n.toLocaleString("es-AR", { maximumFractionDigits: 0 });
  const csrf = () => (document.cookie.match(/(^|;\s*)csrftoken=([^;]+)/) || [])[2] || "";
  const uuid = () => (crypto.randomUUID ? crypto.randomUUID()
    : "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) =>
      (c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (c / 4)))).toString(16)));
  const toNumber = (v) => { const n = parseFloat(String(v).replace(",", ".")); return n > 0 ? n : 0; };
  const arsOf = (usd) => (usd && CFG.rate ? "≈ $" + money(Math.round(usd * CFG.rate)) : "");
  const opts = (list, selected) => list.map((o) =>
    `<option value="${esc(o.id)}"${String(o.id) === String(selected) ? " selected" : ""}>${esc(o.label)}</option>`).join("");
  const cardLabel = (c) => (c.number && !c.name.includes(c.number) ? `${c.name} ${c.number}` : c.name);
  const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;
  const storage = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* modo privado */ } },
  };

  function flash(text, kind) {
    const box = $("cl-msg");
    box.textContent = text;
    box.className = "cl-msg " + kind;
    box.style.display = "block";
    clearTimeout(flash.timer);
    if (kind === "ok") flash.timer = setTimeout(() => { box.style.display = "none"; }, 5000);
  }

  // Un click cierra el aviso (los de error no se van solos).
  $("cl-msg").addEventListener("click", (e) => { if (isMasiva()) e.currentTarget.style.display = "none"; });

  // ================================================================== store
  const S = {
    setId: null,
    set: null,
    rows: [],          // en el orden del servidor; las copias van detrás de su original
    byUid: new Map(),
    stock: {},         // {card_id: {units, price_usd, by_condition}}
    view: [],          // filas que pasan filtros, ya ordenadas
    page: 0,
    tab: "all",
    q: "",
    rarity: "",
    sort: "number",
    errors: {},        // {uid: mensaje}
    saving: false,
    pendingId: null,   // request_id del guardado en curso (se reusa al reintentar)
    focus: null,       // uid de la fila con foco
    wantSet: null,
    seq: 0,
    // Grupos de precio: [{id, price, color}]. Sobreviven al cambio de set
    // (los "commons a USD 0.5" sirven para todas las expansiones).
    groups: [],
    groupSeq: 0,
    chips: [],         // insignias de acabado que existen en el set cargado
    cols: [],          // columnas de casillas: {chip} (acabado) o {attr} (particularidad)
  };

  const MAX_GROUPS = 6;
  const GROUP_COLORS = ["#7c3aed", "#ea580c", "#0d9488", "#db2777", "#2563eb", "#65a30d"];
  const groupOf = (id) => S.groups.find((g) => g.id === id) || null;
  const groupNumber = (g) => S.groups.indexOf(g) + 1;

  const kindOf = (card) => (card.is_card ? "single" : "sealed");
  const qtyOf = (r) => { const n = parseInt(r.qty, 10); return n > 0 ? n : 0; };
  const priceOf = (r) => toNumber(r.price);
  const isReady = (r) => qtyOf(r) > 0 && priceOf(r) > 0 && (r.kind !== "single" || !!r.cond);
  const extrasOf = (r) => [r.name, r.image_url, r.pc_url, r.description, +r.discount > 0].filter(Boolean).length
    + r.shots.length + (r.kind !== kindOf(r.card) ? 1 : 0);
  const defaultCond = (kind) => (kind === "single" ? CFG.defaultConditionId || "" : "");

  function newRow(card, from) {
    const kind = from ? from.kind : kindOf(card);
    const row = {
      uid: "r" + ++S.seq, card, kind, copyOf: from ? from.uid : null,
      idioma: from ? from.idioma : (S.set && S.set.language) || "",
      // Normal / Holo / Reverse Holo...: el primero de la carta es el por defecto.
      acabado: from ? from.acabado : (card.printings || [])[0] || "",
      cond: from ? from.cond : defaultCond(kind),
      // Una copia es otra unidad física: no hereda firmada, alterada, etc.
      attrs: noAttrs(),
      qty: "", price: from ? from.price : "", group: from ? from.group : null,
      discount: "", description: "",
      name: "", image_url: "", pc_url: "",
      shots: [], token: uuid(), uploading: false, sel: false,
    };
    S.byUid.set(row.uid, row);
    return row;
  }

  // Después de guardar: la fila vuelve a vacía pero conserva la condición.
  function resetRow(r) {
    Object.assign(r, {
      qty: "", price: "", group: null, attrs: noAttrs(), discount: "", description: "", name: "", image_url: "", pc_url: "",
      shots: [], token: uuid(), uploading: false, sel: false,
    });
  }

  // El tilde de cada fila es la confirmación: "esta carta se sube". Guardar
  // sube solo las tildadas; una fila con datos pero sin tildar no se sube.
  const hasChanges = () => S.rows.some((r) => r.sel || qtyOf(r) > 0);
  const pending = () => S.rows.filter((r) => r.sel);
  // Cargadas pero sin tildar: se avisa, para que no se olvide ninguna.
  const unconfirmed = () => S.rows.filter((r) => !r.sel && qtyOf(r) > 0);
  // La categoría "Cargando" de arriba decide si se ven cartas o sellados.
  const currentKind = () => {
    const sel = $("cl-category");
    return (sel && sel.options[sel.selectedIndex] && sel.options[sel.selectedIndex].dataset.kind) || "single";
  };
  const gridKind = () => (["single", "sealed"].includes(currentKind()) ? currentKind() : null);
  const pageCount = () => Math.max(1, Math.ceil(S.view.length / PAGE_SIZE));
  const pageRows = () => S.view.slice(S.page * PAGE_SIZE, (S.page + 1) * PAGE_SIZE);

  function computeView() {
    const kind = gridKind();
    const q = S.q.trim().toLowerCase();
    const order = new Map(S.rows.map((r, i) => [r.uid, i]));
    const list = S.rows.filter((r) => {
      if (!kind || kindOf(r.card) !== kind) return false;
      if (S.rarity && r.card.rarity !== S.rarity) return false;
      if (q && !(r.card.name.toLowerCase().includes(q) || (r.card.number || "").toLowerCase().includes(q))) return false;
      if (S.tab === "upload") return r.sel;
      if (S.tab === "errors") return !!S.errors[r.uid];
      return true;
    });
    const byName = (a, b) => a.card.name.localeCompare(b.card.name, "es", { sensitivity: "base" });
    const byNumber = (a, b) => (a.card.number || "").localeCompare(b.card.number || "", undefined, { numeric: true }) || byName(a, b);
    const cmp = S.sort === "az" ? byName : S.sort === "za" ? (a, b) => byName(b, a) : byNumber;
    // Las copias quedan pegadas a su carta: a igual carta manda el orden de inserción.
    list.sort((a, b) => (a.card.id === b.card.id ? 0 : cmp(a, b)) || order.get(a.uid) - order.get(b.uid));
    S.view = list;
    S.page = Math.min(S.page, pageCount() - 1);
  }

  /** Lo que se va a subir: las tildadas completas. Las tildadas incompletas se cuentan aparte. */
  function totals() {
    let cards = 0, units = 0, usd = 0, incomplete = 0;
    for (const r of pending()) {
      if (!isReady(r)) { incomplete++; continue; }
      const q = qtyOf(r);
      cards++; units += q; usd += priceOf(r) * q;
    }
    return { cards, units, usd, ars: Math.round(usd * (CFG.rate || 0)), incomplete };
  }

  // ================================================================== table
  const rowsBox = $("cm-rows");

  function stockHtml(r) {
    const st = S.stock[r.card.id];
    if (!st || !st.units) return '<span class="cm-stock">—</span>';
    const finishes = r.card.printings && r.card.printings.length > 1 ? st.by_finish || {} : {};
    const parts = [
      ...Object.entries(st.by_condition || {}).map(([cid, n]) => `${CONDITION_SHORT[cid] || "?"} ${n}`),
      ...Object.entries(finishes).map(([a, n]) => `${finishLabel(a)} ${n}`),
      ...(Object.keys(st.by_language || {}).length > 1
        ? Object.entries(st.by_language).map(([l, n]) => `${l.toUpperCase()} ${n}`) : []),
    ].join(" · ");
    // Resalta cuando ya tenés esa misma carta en la condición y el acabado de
    // la fila: al guardar se suma a esa publicación.
    const same = r.kind === "single"
      ? !!(r.cond && (st.by_condition || {})[r.cond]) && (!Object.keys(finishes).length || !!finishes[r.acabado])
      : true;
    const title = `Ya tenés ${st.units} en stock${parts ? ` (${parts})` : ""}` +
      (st.price_usd ? `, hasta USD ${st.price_usd}` : "") +
      (same ? ". Al guardar se suma a esa publicación y se actualiza el precio." : ".");
    return `<span class="cm-stock${same ? " is-same" : ""}" title="${esc(title)}">
      <b>${st.units}</b> · USD ${esc(st.price_usd || "—")}<br>${esc(parts)}</span>`;
  }

  /** Las marquitas de grupo de una fila (o el "+" para crear el primero). */
  function groupCellHtml(r) {
    if (!S.groups.length) {
      return '<button type="button" class="cm-gnew" data-f="newgroup" tabindex="-1" ' +
        'title="Crear un grupo de precio con el precio de esta carta">+</button>';
    }
    return S.groups.map((g) => {
      const n = groupNumber(g);
      const on = r.group === g.id;
      return `<button type="button" class="cm-gdot${on ? " is-on" : ""}" data-g="${g.id}" style="--g:${g.color}"
        tabindex="-1" aria-pressed="${on}"
        title="${on ? "Sacar del" : "Poner en el"} grupo ${n}${toNumber(g.price) ? ` (USD ${toNumber(g.price)})` : ""} · Alt+${n}">${n}</button>`;
    }).join("");
  }

  /**
   * Los checkboxes de acabado y particularidades de la fila, como en TCG Fans:
   * una casilla por cada insignia del encabezado. Las de acabado aparecen solo
   * si la carta tiene ese acabado; marcarla convierte la fila en esa impresión
   * y desmarcarla la devuelve a la de por defecto (son excluyentes).
   */
  function finishCellHtml(r) {
    const single = r.kind === "single";
    const finishBox = (c) => {
      const printing = single ? printingFor(r.card, c) : null;
      if (!printing) return '<span class="cm-finbox is-empty"></span>';
      const on = r.acabado === printing;
      return `<label class="cm-finbox${on ? " is-on" : ""}" style="--c:${c.color}"
                title="${esc(finishLabel(printing))}${c.key === "reverse" ? " (Alt+R)" : ""}">
        <input type="checkbox" data-fin="${esc(printing)}"${on ? " checked" : ""} tabindex="-1"
               aria-label="${esc(finishLabel(printing))}"></label>`;
    };
    // Atributos de la unidad: en toda carta suelta (un sellado no se firma ni se altera).
    const attrBox = (a) => {
      if (!single) return '<span class="cm-finbox is-empty"></span>';
      const on = !!r.attrs[a.field];
      return `<label class="cm-finbox${on ? " is-on" : ""}" style="--c:${attrColor(a)}" title="${esc(a.label)}">
        <input type="checkbox" data-attr="${a.field}"${on ? " checked" : ""} tabindex="-1"
               aria-label="${esc(a.label)}"></label>`;
    };
    return `<div class="cm-fins" data-fins>${S.cols.map((col) => (col.attr ? attrBox(col.attr) : finishBox(col.chip))).join("")}</div>`;
  }

  /** Encabezado de la columna de casillas y la leyenda de abajo. */
  function renderFinishHead() {
    const badges = S.cols.map((col) => (col.attr ? [col.attr, attrColor(col.attr)] : [col.chip, col.chip.color]));
    $("cm-fin-head").innerHTML = badges.map(([c, color]) => badgeHtml(c, color)).join("");
    document.querySelector("#cm-list .cm-table")
      .style.setProperty("--cm-fw", Math.max(30, S.cols.length * 34) + "px");   // 30px + 4px de separación
    $("cm-legend").innerHTML = badges
      .map(([c, color]) => `<span>${badgeHtml(c, color)} ${esc(c.label)}</span>`).join("");
  }

  /** Marca o desmarca un atributo de la unidad (firmada, alterada...). */
  function setAttr(r, field, on) {
    r.attrs[field] = on;
    touch(r);
    const el = rowsBox.querySelector(`.cm-row[data-uid="${r.uid}"]`);
    if (el) el.outerHTML = rowHtml(r, +el.dataset.i);
    renderChrome();
  }

  /** Marca o desmarca un acabado. Desmarcar vuelve al de por defecto de la carta. */
  function setFinish(r, printing, on) {
    r.acabado = on ? printing : (r.card.printings || [])[0] || "";
    touch(r);
    const el = rowsBox.querySelector(`.cm-row[data-uid="${r.uid}"]`);
    if (el) el.outerHTML = rowHtml(r, +el.dataset.i);
    renderChrome();
  }

  /**
   * El nombre de la carta como va a quedar en el producto. En los sets WOTC el
   * catálogo dice "(Unlimited)"; si la fila es una 1st Edition, eso sobra (mismo
   * criterio que catalog/finishes.title en el backend).
   */
  function displayName(r) {
    const label = cardLabel(r.card);
    return r.acabado && r.acabado.startsWith("1st Edition") ? label.replace(" (Unlimited)", "") : label;
  }

  /** El idioma de la fila: selector con bandera, o "Japonés" fijo en un set japonés. */
  function languageCellHtml(r) {
    if (isJapaneseSet()) {
      return `<div class="cm-lang is-fixed" data-f="idioma" tabindex="-1">${flagImg("ja")}<span>Japonés</span></div>`;
    }
    return `<div class="cm-lang">${flagImg(r.idioma)}
      <select data-f="idioma" aria-label="Idioma">${opts(LANGUAGES, r.idioma)}</select>
    </div>`;
  }

  function rowClass(r) {
    return ["cm-row", "cm-cols", isReady(r) && "is-ready", qtyOf(r) > 0 && !isReady(r) && "is-pending",
      r.sel && "is-sel", S.errors[r.uid] && "is-error", r.copyOf && "is-copy",
      S.focus === r.uid && "is-focus"].filter(Boolean).join(" ");
  }

  function rowHtml(r, i) {
    const err = S.errors[r.uid];
    const extras = extrasOf(r);
    const thumb = r.card.thumb
      ? `<div class="cl-thumb" data-peek="${esc(r.card.thumb)}"><img src="${esc(r.card.thumb)}" alt="" width="38" height="53"
           loading="lazy" decoding="async" onload="this.classList.add('is-in')"
           onerror="this.parentNode.removeAttribute('data-peek');this.outerHTML='<span>sin<br>imagen</span>'"></div>`
      : '<div class="cl-thumb"><span>sin<br>imagen</span></div>';
    // Si la fila es otra impresión (reverse, 1st Edition…) o tiene una
    // particularidad, se dice bajo el nombre.
    const alt = r.kind === "single" && r.acabado && r.acabado !== (r.card.printings || [])[0];
    const sub = err ? esc(err)
      : [alt && `<b class="cm-alt" style="--c:${chipOf(r.acabado).color}">${esc(finishLabel(r.acabado))}</b>`,
         ...attrsOn(r).map((a) => `<b class="cm-alt" style="--c:${attrColor(a)}">${esc(a.label)}</b>`),
         r.card.number && "#" + esc(r.card.number), esc(S.set ? S.set.name : "")].filter(Boolean).join(" · ");
    return `<div class="${rowClass(r)}" data-uid="${r.uid}" data-i="${i}" role="row">
      <label class="cm-check"><input type="checkbox" data-f="sel"${r.sel ? " checked" : ""} tabindex="-1" aria-label="Subir esta carta" title="Tildala para subirla"></label>
      <div class="cm-card">
        ${thumb}
        <div class="cm-id">
          <div class="cl-name" title="${esc(cardLabel(r.card))}${r.card.rarity ? " · " + esc(r.card.rarity) : ""}">${esc(r.name || displayName(r))}</div>
          <div class="cl-sub"${err ? ` title="${esc(err)}"` : ""}>${r.copyOf ? "Copia · " : ""}${sub}</div>
        </div>
      </div>
      <span class="cm-rarity" title="${esc(r.card.rarity)}">${esc(r.card.rarity || "—")}</span>
      ${languageCellHtml(r)}
      ${finishCellHtml(r)}
      ${r.kind === "single"
        ? `<select data-f="cond" aria-label="Condición" required><option value="">— condición —</option>${opts(CONDITIONS, r.cond)}</select>`
        : '<span class="cm-na" data-f="cond" tabindex="-1">Sellado</span>'}
      ${stockHtml(r)}
      <input data-f="qty" type="number" inputmode="numeric" min="0" max="${r.kind === "single" ? 99 : 999}"
             placeholder="0" value="${esc(r.qty)}" aria-label="Cantidad">
      <div class="cm-gcell" data-gcell>${groupCellHtml(r)}</div>
      <div class="cm-money">
        <span>USD</span>
        <input data-f="price" type="number" inputmode="decimal" min="0" step="0.01"
               placeholder="0" value="${esc(r.price)}" aria-label="Precio USD">
        <small data-ars>${arsOf(priceOf(r))}</small>
      </div>
      <span class="cm-ok" title="${isReady(r) ? "Lista para subir" : "Falta cantidad, precio o condición"}">✓</span>
      <div class="cm-actions">
        ${r.copyOf
          ? '<button type="button" class="cm-act is-del" data-f="del" tabindex="-1" title="Quitar esta copia">×</button>'
          : r.kind === "single" || !isJapaneseSet()
            ? `<button type="button" class="cm-act" data-f="dup" tabindex="-1"
                       title="Duplicar: ${r.kind === "single" ? "la misma carta en otro detalle, idioma o condición" : "el mismo sellado en otro idioma"} (Ctrl+D)">⧉</button>`
            : ""}
        <button type="button" class="cm-act${extras ? " has-data" : ""}" data-f="adv" tabindex="-1"
                title="Nombre, descripción, descuento, fotos, imagen propia, PriceCharting y tipo">✎${extras || ""}</button>
      </div>
    </div>`;
  }

  /** Dibuja la página actual. Conserva el foco y el cursor del campo activo. */
  function renderRows() {
    const active = document.activeElement;
    const keep = active && rowsBox.contains(active) && active.dataset.f
      ? { uid: active.closest(".cm-row").dataset.uid, f: active.dataset.f } : null;

    const start = S.page * PAGE_SIZE;
    rowsBox.innerHTML = pageRows().map((r, k) => rowHtml(r, start + k)).join("");

    if (keep) {
      const el = rowsBox.querySelector(`.cm-row[data-uid="${keep.uid}"] [data-f="${keep.f}"]`);
      if (el) el.focus({ preventScroll: true });
    }
  }

  /** Actualiza una fila en el lugar (sin redibujar la tabla: no se pierde el foco). */
  function refreshRow(r) {
    const el = rowsBox.querySelector(`.cm-row[data-uid="${r.uid}"]`);
    if (!el) return;
    el.className = rowClass(r);
    // El precio puede venir del grupo: se escribe salvo que lo estés tipeando.
    const price = el.querySelector('[data-f="price"]');
    if (price && document.activeElement !== price && price.value !== r.price) price.value = r.price;
    const gcell = el.querySelector("[data-gcell]");
    if (gcell) gcell.innerHTML = groupCellHtml(r);
    const ars = el.querySelector("[data-ars]");
    if (ars) ars.textContent = arsOf(priceOf(r));
    const ok = el.querySelector(".cm-ok");
    if (ok) ok.title = isReady(r) ? "Lista para subir" : "Falta cantidad, precio o condición";
    const stock = el.querySelector(".cm-stock");
    if (stock) stock.outerHTML = stockHtml(r);
    const lang = el.querySelector(".cm-lang:not(.is-fixed)");
    if (lang) {
      const img = lang.querySelector(".cm-flag");
      if (img) img.remove();
      lang.insertAdjacentHTML("afterbegin", flagImg(r.idioma));
    }
  }

  /** Recalcula qué filas se ven y redibuja todo lo que depende de eso. */
  function render({ toTop = false } = {}) {
    computeView();
    const loaded = S.setId != null;
    $("cm-empty").hidden = loaded;
    $("cm-list").hidden = !loaded;
    $("cm-foot").hidden = !loaded;
    const none = $("cm-none");
    none.hidden = S.view.length > 0;
    none.textContent = !gridKind()
      ? "Esta categoría no sale del catálogo: usá la carga individual (slabs, accesorios y mystery packs van a mano)."
      : S.tab !== "all" || S.q || S.rarity ? "Ninguna carta coincide con estos filtros."
        : gridKind() === "sealed" ? "Este set no tiene sellados en el catálogo." : "Este set no tiene cartas.";
    renderRows();
    renderChrome();
    if (toTop) $("cm-list").scrollIntoView({ block: "start", behavior: "smooth" });
  }

  /** Lo que no es la tabla: contadores, pestañas, páginas, selección, pie. */
  function renderChrome() {
    const kind = gridKind();
    const ofKind = S.rows.filter((r) => kindOf(r.card) === kind);
    const counts = {
      all: ofKind.length,
      upload: pending().length,
      errors: Object.keys(S.errors).length,
    };
    $("cm-count").textContent = `${S.view.length} carta${S.view.length === 1 ? "" : "s"}`;
    document.querySelectorAll("#cm-tabs button").forEach((b) => {
      b.classList.toggle("is-on", b.dataset.tab === S.tab);
      b.querySelector("span").textContent = counts[b.dataset.tab] ? `(${counts[b.dataset.tab]})` : "";
    });
    document.querySelector('#cm-tabs [data-tab="errors"]').hidden = !counts.errors;

    const from = S.view.length ? S.page * PAGE_SIZE + 1 : 0;
    const to = Math.min((S.page + 1) * PAGE_SIZE, S.view.length);
    $("cm-page").textContent = `${from} - ${to} / ${S.view.length}`;
    document.querySelector('#cm-list [data-page="-1"]').disabled = S.page === 0;
    document.querySelector('#cm-list [data-page="1"]').disabled = S.page >= pageCount() - 1;

    const visibleSel = S.view.filter((r) => r.sel).length;
    const all = $("cm-all");
    all.checked = S.view.length > 0 && visibleSel === S.view.length;
    all.indeterminate = visibleSel > 0 && visibleSel < S.view.length;
    renderGroupsBar();

    const t = totals();
    const sinTildar = unconfirmed().length;
    $("cm-total-usd").textContent = "USD " + t.usd.toFixed(2);
    $("cm-total-ars").textContent = "$" + money(t.ars) + " ARS";
    const info = [];
    if (t.cards) info.push(`${plural(t.cards, "carta", "cartas")} · ${plural(t.units, "unidad", "unidades")}`);
    if (t.incomplete) info.push(`${plural(t.incomplete, "tildada incompleta", "tildadas incompletas")}`);
    if (sinTildar) info.push(`${plural(sinTildar, "carta con cantidad sin tildar", "cartas con cantidad sin tildar")}: no se suben`);
    if (t.cards && CFG.rate) info.push(`dólar $${money(CFG.rate)}`);
    $("cm-foot-info").textContent = info.length ? info.join(" · ")
      : "Cargá cantidad y precio, y tildá las cartas que vas a subir.";
    $("cm-foot-info").classList.toggle("is-warn", !!sinTildar || !!t.incomplete);
    const save = $("cm-save");
    save.disabled = S.saving || !(t.cards || t.incomplete);
    if (!S.saving) save.textContent = `Subir ${plural(t.cards, "carta", "cartas")}`;
  }

  // ---------------------------------------------------------- edición en fila
  const rowOf = (el) => { const r = el.closest(".cm-row"); return r ? S.byUid.get(r.dataset.uid) : null; };

  function touch(r) {
    // Un cambio invalida el error marcado y el request_id del intento anterior.
    delete S.errors[r.uid];
    S.pendingId = null;
  }

  rowsBox.addEventListener("input", (e) => {
    const r = rowOf(e.target);
    const f = e.target.dataset.f;
    if (!r || (f !== "qty" && f !== "price")) return;
    r[f] = e.target.value;
    // Un precio a mano saca la carta de su grupo: deja de seguirlo.
    if (f === "price") r.group = null;
    touch(r);
    refreshRow(r);
    renderChrome();
  });

  rowsBox.addEventListener("change", (e) => {
    const r = rowOf(e.target);
    if (!r) return;
    const f = e.target.dataset.f;
    if (e.target.dataset.fin) { setFinish(r, e.target.dataset.fin, e.target.checked); return; }
    if (e.target.dataset.attr) { setAttr(r, e.target.dataset.attr, e.target.checked); return; }
    if (f === "cond" || f === "idioma") { r[f] = e.target.value; touch(r); }
    else if (f === "sel") r.sel = e.target.checked;
    else return;
    refreshRow(r);
    renderChrome();
  });

  rowsBox.addEventListener("click", (e) => {
    const dot = e.target.closest("button[data-g]");
    if (dot) { toggleGroup(rowOf(dot), +dot.dataset.g); return; }
    const btn = e.target.closest("button[data-f]");
    if (!btn) return;
    const r = rowOf(btn);
    if (btn.dataset.f === "newgroup") addGroup(r);
    else if (btn.dataset.f === "adv") openAdv(r);
    else if (btn.dataset.f === "dup") duplicate(r);
    else if (btn.dataset.f === "del") removeCopy(r);
  });

  rowsBox.addEventListener("focusin", (e) => {
    const r = rowOf(e.target);
    if (!r || !e.target.dataset.f) return;
    const prev = S.focus && rowsBox.querySelector(`.cm-row[data-uid="${S.focus}"]`);
    if (prev) prev.classList.remove("is-focus");
    S.focus = r.uid;
    e.target.closest(".cm-row").classList.add("is-focus");
    if (e.target.type === "number") e.target.select();
  });

  /**
   * Otra fila de la misma carta, justo debajo: otro acabado o condición.
   *
   * Lo más común es cargar la otra impresión (la reverse de la normal), así
   * que la copia pasa sola al primer acabado que esa carta todavía no tenga en
   * la tabla. Si ya están todos, es para otra condición: arranca sin elegir.
   */
  function duplicate(r) {
    if (!r || (r.kind !== "single" && isJapaneseSet())) return;
    const copy = newRow(r.card, r);
    const sameCard = S.rows.filter((x) => x.card.id === r.card.id);
    let next = null;
    if (r.kind === "single") {
      const used = new Set(sameCard.map((x) => x.acabado));
      next = (r.card.printings || []).find((a) => !used.has(a));
      if (next) copy.acabado = next;
      else copy.cond = "";
    } else {
      // Un sellado solo se repite en otro idioma: el primero que falte.
      const used = new Set(sameCard.map((x) => x.idioma));
      copy.idioma = (LANGUAGES.find((l) => !used.has(l.id)) || {}).id || copy.idioma;
    }
    // Va detrás de la última copia de esa carta.
    let at = S.rows.indexOf(r);
    while (S.rows[at + 1] && S.rows[at + 1].copyOf === r.uid) at++;
    S.rows.splice(at + 1, 0, copy);
    render();
    const i = S.view.indexOf(copy);
    if (i >= 0) focusCell(i, r.kind !== "single" ? "idioma" : next ? "qty" : "cond");
    if (next) flash(`Copia como ${finishLabel(next)}: cargale cantidad y precio.`, "ok");
  }

  function removeCopy(r) {
    if (!r || !r.copyOf) return;
    if (qtyOf(r) > 0 && !window.confirm("Esta copia tiene cantidad cargada. ¿Quitarla igual?")) return;
    S.rows.splice(S.rows.indexOf(r), 1);
    S.byUid.delete(r.uid);
    delete S.errors[r.uid];
    const i = S.view.indexOf(r);
    render();
    focusCell(Math.max(0, i - 1), "qty");
  }

  // ================================================================== keys
  const isControl = (el) => !!el && (el.tagName === "INPUT" || el.tagName === "SELECT");

  /** Lleva el foco al campo `f` de la fila `i` de la vista, cambiando de página si hace falta. */
  function focusCell(i, f) {
    if (i < 0 || i >= S.view.length) return false;
    const page = Math.floor(i / PAGE_SIZE);
    if (page !== S.page) { S.page = page; renderRows(); renderChrome(); }
    const row = rowsBox.querySelector(`.cm-row[data-i="${i}"]`);
    // Si en esa fila el campo es solo texto (sellado sin condición), el foco
    // va a la cantidad.
    let el = row && row.querySelector(`[data-f="${f}"]`);
    if (!isControl(el)) el = row && row.querySelector('[data-f="qty"]');
    if (!el) return false;
    el.focus({ preventScroll: true });
    el.closest(".cm-row").scrollIntoView({ block: "nearest" });
    return true;
  }

  rowsBox.addEventListener("keydown", (e) => {
    const f = e.target.dataset.f;
    if (!FIELDS.includes(f)) return;
    const i = +e.target.closest(".cm-row").dataset.i;
    const r = S.view[i];
    let to = null, field = f;

    if (e.ctrlKey && (e.key === "d" || e.key === "D")) { e.preventDefault(); duplicate(r); return; }
    // Alt+R: marca o desmarca la reverse de la fila.
    if (e.altKey && e.code === "KeyR") {
      const rev = chipByKey("reverse") && printingFor(r.card, chipByKey("reverse"));
      if (rev && r.kind === "single") {
        e.preventDefault();
        setFinish(r, rev, r.acabado !== rev);
        focusCell(i, f);
      }
      return;
    }
    // Alt+1…6: entra o sale del grupo de precio de ese número.
    if (e.altKey && /^Digit[1-6]$/.test(e.code)) {
      const g = S.groups[+e.code.slice(5) - 1];
      if (g) { e.preventDefault(); toggleGroup(r, g.id); }
      return;
    }
    if (e.ctrlKey && e.key === " ") {
      r.sel = !r.sel;
      refreshRow(r);
      const box = e.target.closest(".cm-row").querySelector('[data-f="sel"]');
      if (box) box.checked = r.sel;
      renderChrome();
      e.preventDefault();
      return;
    }
    if (e.key === "Enter" || e.key === "Tab") to = e.shiftKey ? i - 1 : i + 1;
    else if (e.key === "ArrowDown" && !e.altKey) to = i + 1;
    else if (e.key === "ArrowUp" && !e.altKey) to = i - 1;
    else if (e.altKey && (e.key === "ArrowRight" || e.key === "ArrowLeft")) {
      // Siguiente columna editable de esta fila (se saltean las que son texto).
      const step = e.key === "ArrowRight" ? 1 : FIELDS.length - 1;
      const row = e.target.closest(".cm-row");
      let k = FIELDS.indexOf(f);
      for (let n = 0; n < FIELDS.length; n++) {
        k = (k + step) % FIELDS.length;
        if (isControl(row.querySelector(`[data-f="${FIELDS[k]}"]`))) break;
      }
      field = FIELDS[k];
      to = i;
    } else return;

    // En el borde (primera/última fila) Tab sale de la tabla con normalidad.
    if (to < 0 || to >= S.view.length) { if (e.key !== "Tab") e.preventDefault(); return; }
    e.preventDefault();
    focusCell(to, field);
  });

  // ========================================================= filtros / tabs
  $("cm-tabs").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    S.tab = b.dataset.tab;
    S.page = 0;
    render();
  });
  let qTimer = null;
  $("cm-q").addEventListener("input", (e) => {
    clearTimeout(qTimer);
    qTimer = setTimeout(() => { S.q = e.target.value; S.page = 0; render(); }, 120);
  });
  $("cm-q").addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === "ArrowDown") { e.preventDefault(); focusCell(S.page * PAGE_SIZE, "qty"); }
  });
  $("cm-rarity").addEventListener("change", (e) => { S.rarity = e.target.value; S.page = 0; render(); });
  $("cm-sort").addEventListener("change", (e) => { S.sort = e.target.value; S.page = 0; render(); });
  $("cl-category").addEventListener("change", () => { if (S.setId != null) { S.page = 0; render(); } });
  document.querySelector("#cm-list .cm-pager").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-page]");
    if (!b || b.disabled) return;
    S.page = Math.min(pageCount() - 1, Math.max(0, S.page + +b.dataset.page));
    render({ toTop: true });
  });

  // Seleccionar todo marca las filas de la vista entera (todas las páginas).
  $("cm-all").addEventListener("change", (e) => {
    S.view.forEach((r) => { r.sel = e.target.checked; });
    render();
  });

  // ================================================================= grupos
  // Grupos de precio: "Grupo 1 = USD 30". Cada fila tiene una marquita por
  // grupo; marcarla le pone el precio del grupo, y cambiar el precio del
  // grupo cambia el de todas sus cartas. Escribir un precio a mano en una
  // fila la saca del grupo.
  const groupsBar = $("cm-groups");
  let groupsShape = null;   // qué grupos hay dibujados: si no cambió, no se redibuja

  const membersOf = (g) => S.rows.filter((r) => r.group === g.id);

  function renderGroupsBar() {
    const shape = S.groups.map((g) => g.id).join(",");
    // Redibujar mientras escribís el precio de un grupo te sacaría el foco:
    // si la forma no cambió, solo se actualizan los números.
    if (shape === groupsShape) {
      S.groups.forEach((g) => {
        const count = groupsBar.querySelector(`[data-gcount="${g.id}"]`);
        if (count) count.textContent = plural(membersOf(g).length, "carta", "cartas");
      });
      return;
    }
    groupsShape = shape;
    const groups = S.groups.map((g) => {
      const n = groupNumber(g);
      return `<div class="cm-group" style="--g:${g.color}">
        <b class="cm-gdot is-on" style="--g:${g.color}">${n}</b>
        <div class="cm-money"><span>USD</span>
          <input type="number" min="0" step="0.01" data-gprice="${g.id}" value="${esc(g.price)}"
                 placeholder="Precio" aria-label="Precio USD del grupo ${n}">
        </div>
        <small data-gcount="${g.id}">${plural(membersOf(g).length, "carta", "cartas")}</small>
        <button type="button" class="cm-gdel" data-gdel="${g.id}" title="Borrar el grupo ${n} (las cartas conservan el precio)">×</button>
      </div>`;
    }).join("");
    groupsBar.innerHTML = `
      <span class="cm-groups-title">Grupos de precio</span>
      ${groups || '<span class="cm-groups-hint">Creá un grupo (ej: USD 30) y marcá las cartas con su número.</span>'}
      ${S.groups.length < MAX_GROUPS ? '<button type="button" class="cm-gadd" data-gadd>＋ Grupo</button>' : ""}`;
    // El ancho de la columna "Grupo" depende de cuántas marquitas hay.
    document.querySelector("#cm-list .cm-table")
      .style.setProperty("--cm-gw", Math.max(44, S.groups.length * 26 + 6) + "px");
  }

  /** Un grupo nuevo. Si viene de una fila, toma su precio y la mete adentro. */
  function addGroup(fromRow) {
    if (S.groups.length >= MAX_GROUPS) { flash(`Máximo ${MAX_GROUPS} grupos de precio.`, "err"); return; }
    const used = new Set(S.groups.map((g) => g.color));
    const g = {
      id: ++S.groupSeq,
      price: fromRow ? fromRow.price : "",
      color: GROUP_COLORS.find((c) => !used.has(c)) || GROUP_COLORS[0],
    };
    S.groups.push(g);
    if (fromRow) { fromRow.group = g.id; touch(fromRow); }
    render();
    // Si el grupo nace sin precio, el foco va directo a escribirlo.
    if (!toNumber(g.price)) {
      const input = groupsBar.querySelector(`[data-gprice="${g.id}"]`);
      if (input) input.focus();
    }
  }

  /** Entra o sale del grupo. Al entrar, toma su precio. */
  function toggleGroup(r, gid) {
    const g = groupOf(gid);
    if (!r || !g) return;
    if (r.group === gid) r.group = null;   // sale, conserva el precio
    else { r.group = gid; r.price = g.price; }
    touch(r);
    refreshRow(r);
    renderChrome();
  }

  function setGroupPrice(gid, value) {
    const g = groupOf(gid);
    if (!g) return;
    g.price = value;
    for (const r of membersOf(g)) {
      r.price = value;
      touch(r);
      refreshRow(r);
    }
    renderChrome();
  }

  function removeGroup(gid) {
    const g = groupOf(gid);
    if (!g) return;
    membersOf(g).forEach((r) => { r.group = null; });
    S.groups = S.groups.filter((x) => x !== g);
    render();
  }

  groupsBar.addEventListener("input", (e) => {
    if (e.target.dataset.gprice) setGroupPrice(+e.target.dataset.gprice, e.target.value);
  });
  groupsBar.addEventListener("click", (e) => {
    const t = e.target.closest("button");
    if (!t) return;
    if (t.hasAttribute("data-gadd")) addGroup(null);
    else if (t.dataset.gdel) removeGroup(+t.dataset.gdel);
  });
  groupsBar.addEventListener("keydown", (e) => {
    // Enter en el precio de un grupo vuelve a la tabla para seguir marcando.
    if (e.key === "Enter" && e.target.dataset.gprice) {
      e.preventDefault();
      const i = S.view.findIndex((r) => r.group === +e.target.dataset.gprice);
      focusCell(Math.max(0, i), "qty");
    }
  });

  // ==================================================================== adv
  const adv = $("cm-adv");
  const advBody = $("cm-adv-body");
  let advRow = null;

  function renderAdv() {
    const r = advRow;
    const tip = (t) => `<span style="text-transform:none;letter-spacing:0">${t}</span>`;
    advBody.innerHTML = `
      <label>Tipo de producto</label>
      <select data-a="kind">
        <option value="single"${r.kind === "single" ? " selected" : ""}>Single (carta suelta, con condición)</option>
        <option value="sealed"${r.kind === "sealed" ? " selected" : ""}>Sellado (tin, box, booster...)</option>
      </select>
      <label>Nombre del producto ${tip("(vacío = el del catálogo; con nombre propio va en una publicación aparte)")}</label>
      <input type="text" data-a="name" value="${esc(r.name)}" placeholder="${esc(cardLabel(r.card))}">
      <label>Descripción ${tip("(se ve en la tienda)")}</label>
      <textarea data-a="description" rows="2" placeholder="Ej: leve blanqueo en el borde de atrás">${esc(r.description)}</textarea>
      <label>% Descuento</label>
      <input type="number" data-a="discount" min="0" max="100" value="${esc(r.discount)}" placeholder="0">
      <label>URL de imagen propia ${tip("(opcional, va en una publicación aparte)")}</label>
      <input type="text" data-a="image_url" value="${esc(r.image_url)}" placeholder="https://...">
      ${CFG.cloudinary ? `
      <label>O subí fotos ${tip(`(máx. ${CFG.maxShots})`)}</label>
      <div class="cl-shots">
        ${r.shots.map((u) => `<img class="cl-shot" src="${esc(u)}" alt="">`).join("")}
        ${r.shots.length < CFG.maxShots ? `<label class="cl-upload"><input type="file" data-a="file" accept="image/*">
          ${r.uploading ? "Subiendo..." : "＋ Subir foto"}</label>` : ""}
      </div>` : ""}
      <label>URL de PriceCharting ${tip("(opcional)")}</label>
      <input type="text" data-a="pc_url" value="${esc(r.pc_url)}" placeholder="https://www.pricecharting.com/...">
      <div class="cl-note">Si no cargás foto ni URL, se usa la imagen del catálogo y la cantidad se suma a la publicación que ya tengas de esa carta en esa condición.</div>`;
  }

  function openAdv(r) {
    if (!r) return;
    advRow = r;
    $("cm-adv-title").textContent = cardLabel(r.card);
    renderAdv();
    adv.showModal();
  }

  advBody.addEventListener("input", (e) => {
    const k = e.target.dataset.a;
    if (!advRow || !["name", "image_url", "pc_url", "description", "discount"].includes(k)) return;
    advRow[k] = e.target.value.trim() ? e.target.value : "";
    touch(advRow);
  });
  advBody.addEventListener("change", (e) => {
    const k = e.target.dataset.a;
    if (!advRow) return;
    if (k === "kind") {
      advRow.kind = e.target.value;
      advRow.cond = advRow.kind === "single" ? advRow.cond || defaultCond("single") : "";
    } else if (k === "file") { uploadShot(advRow, e.target.files[0]); return; }
    else return;
    touch(advRow);
  });
  adv.addEventListener("click", (e) => { if (e.target.closest("[data-close]")) adv.close(); });
  adv.addEventListener("close", () => {
    const r = advRow;
    advRow = null;
    render();
    if (r) { const i = S.view.indexOf(r); if (i >= 0) focusCell(i, "qty"); }
  });

  // Mismo camino que el lote y el form clásico: firmar, subir directo a
  // Cloudinary y registrar la ProductImage contra el token de la fila.
  async function uploadShot(r, file) {
    if (!file || r.shots.length >= CFG.maxShots) return;
    const post = (url, body) => fetch(url, {
      method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: JSON.stringify(body),
    });
    r.uploading = true;
    if (advRow === r) renderAdv();
    try {
      const slot = r.shots.length;
      const sigRes = await post(CFG.signUrl, { draft_token: r.token, slot });
      if (!sigRes.ok) throw new Error((await sigRes.json()).detail || "no se pudo firmar la subida");
      const sig = await sigRes.json();
      const form = new FormData();
      form.append("file", file);
      ["api_key", "timestamp", "upload_preset", "context", "notification_url", "signature"]
        .forEach((k) => form.append(k, sig[k]));
      const upRes = await fetch(sig.upload_url, { method: "POST", body: form });
      if (!upRes.ok) throw new Error("Cloudinary rechazó la foto");
      const up = await upRes.json();
      const regRes = await post(CFG.registerUrl, {
        draft_token: r.token, secure_url: up.secure_url, public_id: up.public_id,
        order_index: slot, source: "cloudinary",
      });
      if (!regRes.ok) throw new Error((await regRes.json()).detail || "no se pudo registrar la foto");
      r.shots.push(up.secure_url);
      touch(r);
    } catch (err) {
      flash("Foto no subida: " + err.message, "err");
    } finally {
      r.uploading = false;
      if (advRow === r) renderAdv();
    }
  }

  // ==================================================================== api
  let loadCtl = null;

  async function loadSet(id) {
    if (loadCtl) loadCtl.abort();
    const ctl = new AbortController();
    loadCtl = ctl;
    $("cm-empty").hidden = false;
    $("cm-empty").textContent = "Trayendo el set...";
    let data;
    try {
      const res = await fetch(CFG.setUrl.replace(/\/0\/$/, `/${encodeURIComponent(id)}/`), { signal: ctl.signal });
      data = await res.json();
      if (!res.ok) throw new Error(data.error || "No se pudo traer el set.");
    } catch (err) {
      if (err.name === "AbortError") return;
      flash(err.message || "Error de red trayendo el set.", "err");
      $("cm-empty").textContent = "No se pudo traer el set. Probá de nuevo.";
      return;
    } finally {
      if (loadCtl === ctl) loadCtl = null;
    }

    S.setId = data.set.id;
    S.set = data.set;
    S.byUid = new Map();
    S.rows = data.cards.map((c) => newRow(c));
    S.stock = data.stock || {};
    S.errors = {};
    S.pendingId = null;
    S.tab = "all"; S.q = ""; S.rarity = ""; S.focus = null; S.page = 0;
    $("cm-q").value = "";
    const rarities = [...new Set(data.cards.map((c) => c.rarity).filter(Boolean))].sort();
    // Insignias de acabado del set: las de los acabados alternativos que tiene
    // alguna de sus cartas, en el orden de la lista del backend.
    const chips = new Map();
    data.cards.forEach((c) => altFinishes(c).forEach((a) => { const ch = chipOf(a); chips.set(ch.key, ch); }));
    const order = (c) => { const k = CHIPS.findIndex((x) => x.key === c.key); return k < 0 ? CHIPS.length : k; };
    S.chips = [...chips.values()].sort((a, b) => order(a) - order(b));
    // Columnas: las fijas (en todos los sets) y después los otros acabados del set.
    const fixed = (k) => { const c = chipByKey(k); return c ? [{ chip: c }] : []; };
    S.cols = [...fixed("reverse"), ...ATTRS.map((a) => ({ attr: a })), ...fixed("1st"),
              ...S.chips.filter((c) => !FIXED_CHIPS.includes(c.key)).map((c) => ({ chip: c }))];
    renderFinishHead();
    $("cm-rarity").innerHTML = '<option value="">Todas las rarezas</option>' +
      rarities.map((x) => `<option>${esc(x)}</option>`).join("");
    render();
    // Si el set no tiene del tipo elegido arriba pero sí del otro, se avisa.
    if (!S.view.length && S.rows.length && gridKind()) {
      flash(`Este set no tiene ${gridKind() === "single" ? "cartas" : "sellados"}: cambiá «Cargando» arriba.`, "warn");
    }
    focusCell(0, "qty");
  }

  /**
   * Chequeos del lado del cliente antes de revisar y antes de subir. El
   * servidor valida todo de nuevo; esto solo ahorra el viaje en lo obvio.
   * Si algo falla, lo marca en la tabla y devuelve false.
   */
  function canUpload(rows) {
    if (!rows.length) return false;
    const bad = {};
    // Tildada = se sube: tiene que estar completa.
    rows.forEach((r) => {
      if (!qtyOf(r)) bad[r.uid] = "Tildada sin cantidad.";
      else if (!(priceOf(r) > 0)) bad[r.uid] = "Falta el precio.";
      else if (r.kind === "single" && !r.cond) bad[r.uid] = "Falta la condición.";
    });
    // La misma carta en la misma condición dos veces: ¿el precio de cuál?
    const seen = new Map();
    rows.forEach((r) => {
      if (bad[r.uid] || r.name || r.image_url || r.shots.length) return;
      const key = r.kind === "single"
        ? `${r.card.id}|single|${r.idioma}|${r.cond}|${r.acabado}|${attrsOn(r).map((a) => a.field).join(",")}`
        : `${r.card.id}|sealed|${r.idioma}`;
      if (seen.has(key)) bad[r.uid] = "Esta carta ya está en otra fila igual (idioma, condición, detalle y particularidades): sumá las cantidades.";
      else seen.set(key, r);
    });
    if (Object.keys(bad).length) {
      S.errors = bad;
      S.tab = "errors";
      S.page = 0;
      render({ toTop: true });
      flash(`Hay ${plural(Object.keys(bad).length, "carta tildada con un problema", "cartas tildadas con problemas")}: corregila o destildala. No se subió nada.`, "err");
      return false;
    }
    const units = rows.reduce((n, r) => n + qtyOf(r), 0);
    if (rows.length > CFG.maxRows || units > CFG.maxUnits) {
      flash(`Máximo ${CFG.maxRows} filas y ${CFG.maxUnits} unidades por subida. Subilas en tandas.`, "err");
      return false;
    }
    if (rows.some((r) => r.uploading)) { flash("Esperá a que terminen de subir las fotos.", "err"); return false; }
    return true;
  }

  // ================================================================= review
  // Nada impacta en el stock sin pasar por la revisión: se ve todo lo tildado,
  // se puede corregir cantidad, precio o condición, o quitar una carta, y
  // recién "Confirmar y subir" guarda. Lo que se cambia acá cambia la fila.
  const review = $("cm-review");
  const reviewBody = $("cm-review-body");

  /** ¿Se suma a una publicación que ya existe? (misma carta y condición, sin nada propio). */
  function addsToExisting(r) {
    if (r.name || r.image_url || r.shots.length) return false;
    const st = S.stock[r.card.id];
    if (!st || !st.units || attrsOn(r).length) return false;
    if (Object.keys(st.by_language || {}).length && !(st.by_language || {})[r.idioma]) return false;
    if (r.kind !== "single") return true;
    const multi = r.card.printings && r.card.printings.length > 1;
    return !!(st.by_condition || {})[r.cond] && (!multi || !!(st.by_finish || {})[r.acabado]);
  }

  function reviewRowHtml(r) {
    const extra = [
      flagImg(r.idioma, "cm-flag-inline"),
      r.kind === "single" && r.acabado && r.acabado !== (r.card.printings || [])[0]
        ? `<b class="cm-alt" style="--c:${chipOf(r.acabado).color}">${esc(finishLabel(r.acabado))}</b>` : "",
      ...attrsOn(r).map((a) => `<b class="cm-alt" style="--c:${attrColor(a)}">${esc(a.label)}</b>`),
      r.kind === "sealed" ? "Sellado" : "",
      +r.discount > 0 ? `${+r.discount}% off` : "",
      addsToExisting(r) ? '<span class="cm-review-tag">Suma al stock existente</span>' : "",
      r.card.number ? "#" + esc(r.card.number) : "",
    ].filter(Boolean).join(" · ");
    return `<div class="cm-review-cols cm-review-row" data-uid="${r.uid}">
      <div class="cl-thumb is-mini">${r.card.thumb ? `<img src="${esc(r.card.thumb)}" alt="" class="is-in" loading="lazy">` : ""}</div>
      <div class="cm-id">
        <div class="cl-name">${esc(r.name || displayName(r))}</div>
        <div class="cl-sub">${extra}</div>
      </div>
      ${r.kind === "single"
        ? `<select data-r="cond" aria-label="Condición">${opts(CONDITIONS, r.cond)}</select>`
        : '<span class="cm-na">—</span>'}
      <input data-r="qty" type="number" min="1" max="${r.kind === "single" ? 99 : 999}" value="${esc(r.qty)}" aria-label="Cantidad">
      <div class="cm-money"><span>USD</span>
        <input data-r="price" type="number" min="0" step="0.01" value="${esc(r.price)}" aria-label="Precio USD">
      </div>
      <b class="cm-review-sub" data-sub>${reviewSubtotal(r)}</b>
      <button type="button" class="cm-act is-del" data-r="remove" title="Quitar de esta subida (queda destildada en la tabla)">×</button>
    </div>`;
  }

  function reviewSubtotal(r) {
    const usd = priceOf(r) * qtyOf(r);
    return usd ? `USD ${usd.toFixed(2)}<small>$${money(Math.round(usd * (CFG.rate || 0)))}</small>` : "—";
  }

  function renderReviewTotals() {
    const rows = pending();
    const t = totals();
    $("cm-review-title").textContent = `Revisá antes de subir · ${plural(rows.length, "carta", "cartas")}`;
    $("cm-review-total").innerHTML = rows.length
      ? `${plural(t.units, "unidad", "unidades")} · <b>USD ${t.usd.toFixed(2)}</b> · <b>$${money(t.ars)} ARS</b>` +
        (t.incomplete ? ` · <span class="is-warn">${plural(t.incomplete, "carta incompleta", "cartas incompletas")}</span>` : "")
      : "No queda nada para subir.";
    const ok = $("cm-review-confirm");
    ok.disabled = !t.cards || !!t.incomplete;
    ok.textContent = `Confirmar y subir ${plural(t.cards, "carta", "cartas")}`;
  }

  function openReview() {
    if (S.saving || !canUpload(pending())) return;
    reviewBody.innerHTML = pending().map(reviewRowHtml).join("");
    renderReviewTotals();
    review.showModal();
    $("cm-review-confirm").focus();
  }

  reviewBody.addEventListener("input", (e) => {
    const el = e.target.closest(".cm-review-row");
    const r = el && S.byUid.get(el.dataset.uid);
    const f = e.target.dataset.r;
    if (!r || (f !== "qty" && f !== "price")) return;
    r[f] = e.target.value;
    if (f === "price") r.group = null;   // un precio a mano sale del grupo, igual que en la tabla
    touch(r);
    el.querySelector("[data-sub]").innerHTML = reviewSubtotal(r);
    renderReviewTotals();
  });
  reviewBody.addEventListener("change", (e) => {
    const el = e.target.closest(".cm-review-row");
    const r = el && S.byUid.get(el.dataset.uid);
    if (r && e.target.dataset.r === "cond") { r.cond = e.target.value; touch(r); renderReviewTotals(); }
  });
  reviewBody.addEventListener("click", (e) => {
    const btn = e.target.closest('[data-r="remove"]');
    if (!btn) return;
    const el = btn.closest(".cm-review-row");
    const r = S.byUid.get(el.dataset.uid);
    if (r) { r.sel = false; touch(r); }
    el.remove();
    renderReviewTotals();
    if (!pending().length) review.close();
  });
  review.addEventListener("click", (e) => { if (e.target.closest("[data-close]")) review.close(); });
  // Al cerrar, la tabla refleja lo que se corrigió o quitó en la revisión.
  review.addEventListener("close", () => { if (!S.saving) render(); });
  $("cm-review-confirm").addEventListener("click", () => {
    if (!canUpload(pending())) { review.close(); return; }
    review.close();
    save();
  });

  async function save() {
    if (S.saving) return;
    const rows = pending();
    if (!canUpload(rows)) return;

    // Un id por intento: si la respuesta se pierde y reintentás, el servidor
    // devuelve lo que ya guardó en vez de cargar todo de nuevo.
    S.pendingId = S.pendingId || uuid();
    S.saving = true;
    const btn = $("cm-save");
    btn.disabled = true;
    btn.classList.add("is-loading");
    btn.textContent = "Subiendo...";

    try {
      const res = await fetch(CFG.saveUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
        body: JSON.stringify({
          request_id: S.pendingId,
          items: rows.map((r) => ({
            key: r.uid,
            card_id: r.card.id,
            kind: r.kind,
            quantity: qtyOf(r),
            price_usd: priceOf(r),
            condition_id: r.kind === "single" ? r.cond || null : null,
            // En un set japonés el idioma no se elige: lo pone el servidor.
            language: isJapaneseSet() ? "" : r.idioma,
            finish: r.kind === "single" ? r.acabado : "",
            ...Object.fromEntries(ATTRS.map((a) => [a.field, r.kind === "single" && !!r.attrs[a.field]])),
            discount_percent: parseInt(r.discount, 10) || 0,
            description: r.description,
            name: r.name,
            image_url: r.image_url,
            pricecharting_url: r.pc_url,
            draft_token: r.shots.length ? r.token : "",
          })),
        }),
      });
      const data = await res.json().catch(() => ({}));

      if (res.status === 400) {
        // Validación: no se guardó nada, así que el próximo intento es otro.
        S.pendingId = null;
        S.errors = { ...(data.errors || {}) };
        if (Object.keys(S.errors).length) { S.tab = "errors"; S.page = 0; }
        flash(data.error || "No se pudo guardar.", "err");
        return;
      }
      if (!res.ok) throw new Error(data.error || `El servidor respondió ${res.status}.`);

      Object.assign(S.stock, data.stock || {});
      rows.forEach(resetRow);
      S.errors = {};
      S.pendingId = null;
      if (S.tab === "upload" || S.tab === "errors") S.tab = "all";
      const parts = [];
      if (data.created) parts.push(`${plural(data.created, "publicación nueva", "publicaciones nuevas")}`);
      if (data.updated) parts.push(`${plural(data.updated, "publicación con stock sumado", "publicaciones con stock sumado")}`);
      flash(`Listo: ${parts.join(", ") || "nada nuevo"} (${plural(data.units, "unidad", "unidades")}).` +
        (data.repeated ? " Ya estaba guardado: no se duplicó nada." : ""), "ok");
      // La búsqueda de la carga individual tiene el "ya tenés N" viejo.
      document.dispatchEvent(new CustomEvent("cl:stock-changed"));
    } catch (err) {
      // Red caída o 5xx: no sabemos si llegó. Se conserva el request_id para
      // que el reintento no duplique.
      flash(`No se pudo confirmar el guardado (${err.message}). Volvé a apretar Subir: no se va a duplicar.`, "err");
    } finally {
      S.saving = false;
      btn.classList.remove("is-loading");
      render();
    }
  }
  // "Subir" abre la revisión; recién "Confirmar y subir" guarda.
  $("cm-save").addEventListener("click", openReview);

  // ================================================== modo y cambios de set
  const CONFIRM = "Tenés cartas con cantidad cargada sin guardar en la carga masiva. ¿Descartarlas?";
  const isMasiva = () => wrap.classList.contains("is-masiva");

  document.addEventListener("cl:before-set-change", (e) => {
    if (!e.detail.id || String(e.detail.id) === String(S.setId)) return;
    if (hasChanges() && !window.confirm(CONFIRM)) e.preventDefault();
  });
  document.addEventListener("cl:set-change", (e) => {
    const id = e.detail.id;
    // Vaciar la expansión no borra la tabla: lo cargado sigue ahí.
    if (!id || String(id) === String(S.setId)) return;
    if (isMasiva()) loadSet(id);
    else S.wantSet = id;
  });

  window.addEventListener("beforeunload", (e) => {
    if (hasChanges()) { e.preventDefault(); e.returnValue = ""; }
  });

  function setMode(mode) {
    wrap.classList.toggle("is-masiva", mode === "masiva");
    document.querySelectorAll("#cm-modes [data-mode]").forEach((b) => {
      b.classList.toggle("is-on", b.dataset.mode === mode);
      b.setAttribute("aria-selected", String(b.dataset.mode === mode));
    });
    storage.set(MODE_KEY, mode);
    if (mode !== "masiva") return;
    const barSet = ($("cl-set") || {}).value || S.wantSet;
    S.wantSet = null;
    if (barSet && String(barSet) !== String(S.setId)) loadSet(barSet);
    else render();
    // En la masiva el foco va a la expansión si todavía no hay set.
    if (!barSet && !S.setId) { const input = $("cl-set-input"); if (input) input.focus(); }
  }
  $("cm-modes").addEventListener("click", (e) => {
    const b = e.target.closest("[data-mode]");
    if (b && !b.classList.contains("is-on")) setMode(b.dataset.mode);
  });

  setMode(storage.get(MODE_KEY) === "masiva" ? "masiva" : "lote");
})();
