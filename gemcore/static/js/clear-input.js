"use strict";

// Delegation keeps clearing local even after the search form is replaced.
document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-clear-input]");
    if (!button) {
        return;
    }
    const input = button.form?.elements.namedItem(button.dataset.clearInput);
    if (input && !input.disabled && !input.readOnly) {
        input.value = "";
        input.focus();
    }
});
