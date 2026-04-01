(function () {
  function normalizeText(value) {
    return (value || '').trim().toLowerCase();
  }

  function isUniqueCategory(categorySelect) {
    if (!categorySelect) return false;
    var option = categorySelect.options[categorySelect.selectedIndex];
    var label = normalizeText(option ? option.text : '');
    return label === 'single' || label === 'singles' || label === 'slab' || label === 'slabs';
  }

  function applyStockState() {
    var categorySelect = document.getElementById('id_category');
    var stockInput = document.getElementById('id_stock_quantity');
    var inStockCheckbox = document.getElementById('id_in_stock');

    if (!categorySelect || !stockInput || !inStockCheckbox) return;

    var unique = isUniqueCategory(categorySelect);

    if (unique) {
      stockInput.value = inStockCheckbox.checked ? '1' : '0';
      stockInput.readOnly = true;
      stockInput.setAttribute('aria-readonly', 'true');
      stockInput.classList.add('vTextField--readonly');
      stockInput.style.backgroundColor = '#f5f5f5';
      stockInput.style.color = '#111111';
      stockInput.style.webkitTextFillColor = '#111111';
      stockInput.title = 'Para Singles/Slabs el stock se fija automáticamente.';
    } else {
      stockInput.readOnly = false;
      stockInput.removeAttribute('aria-readonly');
      stockInput.classList.remove('vTextField--readonly');
      stockInput.style.backgroundColor = '';
      stockInput.style.color = '';
      stockInput.style.webkitTextFillColor = '';
      stockInput.title = '';
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    var categorySelect = document.getElementById('id_category');
    var inStockCheckbox = document.getElementById('id_in_stock');

    if (categorySelect) {
      categorySelect.addEventListener('change', applyStockState);
    }
    if (inStockCheckbox) {
      inStockCheckbox.addEventListener('change', applyStockState);
    }

    applyStockState();
  });
})();
