var currency_mapping = {
    '1': 'AR',
    '2': 'AR',
    '6': 'AR',
    '7': 'AR',
    '12': 'AR',
    '3': 'UY',
    '11': 'UY',
    '19': 'UY',
    '20': 'UY',
    '22': 'UY',
    '23': 'UY',
    '24': 'UY',
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
        if (current.length > 0 && current[current.length - 1] != ','){
            current = current + ','
        }
        value = strip(value);
        input.val(current + value + ',');
        return false;
    });

    function update_country_from_account(account_field) {
        var country = currency_mapping[account_field.val()];
        $('#id_country').val(country);
    }

    $('#id_account').change(
        function() {update_country_from_account($(this))});

    update_country_from_account($('#id_account'));

});
