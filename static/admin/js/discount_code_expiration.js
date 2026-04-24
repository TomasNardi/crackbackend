(function () {
  function getExpirationTypeField() {
    return document.getElementById("id_expiration_type");
  }

  function getDateInputs(fieldName) {
    return Array.from(
      document.querySelectorAll(
        "[name='" + fieldName + "'], [name^='" + fieldName + "_']"
      )
    );
  }

  function toggleField(fieldName, disabled) {
    var inputs = getDateInputs(fieldName);
    inputs.forEach(function (input) {
      input.disabled = disabled;
      if (disabled) {
        input.value = "";
      }
    });
  }

  function syncExpirationFields() {
    var expirationTypeField = getExpirationTypeField();
    if (!expirationTypeField) {
      return;
    }

    var isNoExpiration = expirationTypeField.value === "none";
    toggleField("valid_from", isNoExpiration);
    toggleField("valid_until", isNoExpiration);
  }

  document.addEventListener("DOMContentLoaded", function () {
    var expirationTypeField = getExpirationTypeField();
    if (!expirationTypeField) {
      return;
    }

    syncExpirationFields();
    expirationTypeField.addEventListener("change", syncExpirationFields);
  });
})();
