// Native calendar for ISODateInput (templates/forms/iso_date.html).
//
// The visible field is a text input, so the date always reads YYYY-MM-DD
// regardless of browser locale. A hidden date input lends its calendar.
// Listeners are delegated so content swapped in works without any setup.
"use strict";
{
    const find = (target) => {
        const root = target.closest("[data-iso-date]");
        if (!root) {
            return null;
        }
        const picker = root.querySelector('input[type="date"]');
        const text = root.querySelector('input:not([type="date"])');
        return picker && text ? {picker, text} : null;
    };

    // Clicking the text field or the calendar button opens the calendar.
    document.addEventListener("click", (event) => {
        if (!event.target.closest('input:not([type="date"]), button')) {
            return;
        }
        const found = find(event.target);
        if (!found || found.text.disabled || found.text.readOnly) {
            return;
        }
        // Anything but a complete valid date leaves the picker empty.
        found.picker.value = found.text.value;
        try {
            found.picker.showPicker();
        } catch (error) {
            // No showPicker() support, or the browser refused: typing works.
        }
    });

    // Picking a day in the calendar writes it back as YYYY-MM-DD.
    document.addEventListener("change", (event) => {
        if (!event.target.matches('[data-iso-date] input[type="date"]')) {
            return;
        }
        const found = find(event.target);
        if (found) {
            found.text.value = found.picker.value;
        }
    });
}
