(function () {
  'use strict';

  const MAX_SUGGESTED_PRODUCTS = 3;
  const SOURCE_SELECT_ID = 'id_suggested_products_from';
  const TARGET_SELECT_ID = 'id_suggested_products_to';
  const FIELD_WRAPPER_ID = 'id_suggested_products_selector';
  const STATUS_CLASS = 'suggested-products-limit-status';
  const STATUS_REACHED_CLASS = 'suggested-products-limit-status--reached';

  let isSyncing = false;

  function getSelectBoxes() {
    const sourceSelect = document.getElementById(SOURCE_SELECT_ID);
    const targetSelect = document.getElementById(TARGET_SELECT_ID);

    if (!sourceSelect || !targetSelect) {
      return null;
    }

    return { sourceSelect, targetSelect };
  }

  function getControls() {
    return {
      addButton: document.getElementById('id_suggested_products_add_link'),
      addAllButton: document.getElementById('id_suggested_products_add_all_link'),
      removeButton: document.getElementById('id_suggested_products_remove_link'),
      removeAllButton: document.getElementById('id_suggested_products_remove_all_link'),
    };
  }

  function ensureStatusNode(fieldWrapper) {
    let statusNode = fieldWrapper.querySelector('.' + STATUS_CLASS);
    if (statusNode) {
      return statusNode;
    }

    statusNode = document.createElement('p');
    statusNode.className = STATUS_CLASS;
    statusNode.style.marginTop = '8px';
    statusNode.style.fontSize = '12px';
    statusNode.style.lineHeight = '1.4';
    statusNode.style.color = 'rgb(107 101 96)';
    fieldWrapper.appendChild(statusNode);

    return statusNode;
  }

  function updateStatus(fieldWrapper, selectedCount) {
    const statusNode = ensureStatusNode(fieldWrapper);
    const remaining = Math.max(MAX_SUGGESTED_PRODUCTS - selectedCount, 0);
    const limitReached = selectedCount >= MAX_SUGGESTED_PRODUCTS;

    statusNode.textContent = limitReached
      ? 'Ya elegiste 3 de 3 productos. Quitá uno para agregar otro.'
      : 'Podés elegir hasta 3 productos. Te quedan ' + remaining + '.';

    statusNode.classList.toggle(STATUS_REACHED_CLASS, limitReached);
    statusNode.style.color = limitReached ? '#C8972E' : 'rgb(107 101 96)';
  }

  function setControlState(control, disabled) {
    if (!control) {
      return;
    }

    control.classList.toggle('disabled', disabled);
    control.setAttribute('aria-disabled', disabled ? 'true' : 'false');
    control.style.pointerEvents = disabled ? 'none' : '';
    control.style.opacity = disabled ? '0.45' : '';
  }

  function updateUIState(fieldWrapper) {
    const selectBoxes = getSelectBoxes();
    if (!selectBoxes) {
      return;
    }

    const { sourceSelect, targetSelect } = selectBoxes;
    const { addButton, addAllButton, removeButton, removeAllButton } = getControls();
    const selectedCount = targetSelect.options.length;
    const limitReached = selectedCount >= MAX_SUGGESTED_PRODUCTS;

    sourceSelect.disabled = limitReached;
    setControlState(addButton, limitReached);
    setControlState(addAllButton, limitReached);
    setControlState(removeButton, selectedCount === 0);
    setControlState(removeAllButton, selectedCount === 0);
    updateStatus(fieldWrapper, selectedCount);
  }

  function syncSelectBox(selectElement) {
    if (!window.SelectBox || !SelectBox.cache) {
      return;
    }

    SelectBox.cache[selectElement.id] = Array.from(selectElement.options).map((option) => ({
      value: option.value,
      text: option.text,
      displayed: 1,
    }));

    if (typeof SelectBox.sort === 'function') {
      SelectBox.sort(selectElement.id);
    }

    if (typeof SelectBox.redisplay === 'function') {
      SelectBox.redisplay(selectElement.id);
    }
  }

  function enforceLimit(fieldWrapper) {
    const selectBoxes = getSelectBoxes();
    if (!selectBoxes || isSyncing) {
      return;
    }

    const { sourceSelect, targetSelect } = selectBoxes;
    const overflowOptions = Array.from(targetSelect.options).slice(MAX_SUGGESTED_PRODUCTS);

    if (!overflowOptions.length) {
      return;
    }

    isSyncing = true;

    overflowOptions.forEach((option) => {
      option.selected = false;
      sourceSelect.appendChild(option);
    });

    syncSelectBox(sourceSelect);
    syncSelectBox(targetSelect);
    isSyncing = false;
    updateUIState(fieldWrapper);
  }

  function init() {
    const fieldWrapper = document.getElementById(FIELD_WRAPPER_ID);
    const selectBoxes = getSelectBoxes();

    if (!fieldWrapper || !selectBoxes) {
      return;
    }

    const observer = new MutationObserver(function () {
      enforceLimit(fieldWrapper);
      updateUIState(fieldWrapper);
    });
    observer.observe(selectBoxes.targetSelect, { childList: true });

    fieldWrapper.addEventListener('dblclick', function () {
      window.setTimeout(function () {
        enforceLimit(fieldWrapper);
        updateUIState(fieldWrapper);
      }, 0);
    });

    fieldWrapper.addEventListener('click', function () {
      window.setTimeout(function () {
        enforceLimit(fieldWrapper);
        updateUIState(fieldWrapper);
      }, 0);
    });

    enforceLimit(fieldWrapper);
    updateUIState(fieldWrapper);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();