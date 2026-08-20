(function () {
  // El stock de un single o un slab ya no está clavado en 1: tener la misma
  // carta repetida en el mismo estado es UNA publicación con stock N. Lo único
  // que se sincroniza acá es la coherencia entre "En stock" y la cantidad, para
  // que no quedes con el checkbox tildado y 0 unidades.
  function normalizeText(value) {
    return (value || '').trim().toLowerCase();
  }

  function isUniqueCategory(categorySelect) {
    if (!categorySelect) return false;
    var option = categorySelect.options[categorySelect.selectedIndex];
    var label = normalizeText(option ? option.text : '');
    return label === 'single' || label === 'singles' || label === 'slab' || label === 'slabs';
  }

  function elements() {
    return {
      category: document.getElementById('id_category'),
      stock: document.getElementById('id_stock_quantity'),
      inStock: document.getElementById('id_in_stock'),
    };
  }

  function onStockChange() {
    var el = elements();
    if (!el.stock || !el.inStock) return;

    var raw = el.stock.value.trim();
    if (raw === '') return;

    el.inStock.checked = parseInt(raw, 10) > 0;
  }

  function onInStockChange() {
    var el = elements();
    if (!el.stock || !el.inStock) return;

    // Destildar "En stock" es la forma rápida de pausar una publicación.
    if (!el.inStock.checked) {
      el.stock.value = '0';
      return;
    }

    // Al volver a publicar, un single sin cantidad arranca en 1 (el caso normal).
    var raw = el.stock.value.trim();
    if (raw === '' || parseInt(raw, 10) === 0) {
      el.stock.value = isUniqueCategory(el.category) ? '1' : '';
    }
  }

  function applyHelp() {
    var el = elements();
    if (!el.stock) return;
    el.stock.title = 'Unidades de esta publicación. Repetidas del mismo estado van acá, no en una publicación nueva.';
  }

  document.addEventListener('DOMContentLoaded', function () {
    var el = elements();
    if (el.stock) el.stock.addEventListener('change', onStockChange);
    if (el.inStock) el.inStock.addEventListener('change', onInStockChange);
    applyHelp();
  });
})();
