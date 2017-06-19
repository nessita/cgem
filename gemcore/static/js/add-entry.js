var currency_mapping = {
    'ARS': 'AR',
    'CAD': 'CA',
    'USD': 'US',
    'UYU': 'UY',
}

$(document).ready(function() {
    $('input.datepicker').datepicker({
        format: "yyyy-mm-dd",
        autoclose: true,
        todayHighlight: true
    });

    function strip(str){
        return str.replace(/^\s+|\s+$/g, '');
    }

    $('.tags a').click(function() {
        var value = $(this).text();
        var input = $('#id_tags');
        var current = strip(input.val());
        if (current.length > 0 && current[current.length - 1] != ',') {
            current = current + ','
        }
        value = strip(value);
        input.val(current + value + ',');
        return false;
    });

    function update_country_from_account(account_field) {
        var account_label = $('#id_account option:selected').text()
        if (!account_label) return

        for (var key in currency_mapping) {
            if (account_label.indexOf(key) >= 0) {
                $('#id_country').val(currency_mapping[key]);
            }
        }
    }

    $('#id_account').change(
        function() {update_country_from_account($(this))});

    // only set country on load if there is no country set
    if (!$('#id_country').val()){
        update_country_from_account($('#id_account'));
    }

});
