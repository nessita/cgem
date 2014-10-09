var currency_mapping = {
    '1': 'AR',
    '2': 'AR',
    '6': 'AR',
    '7': 'AR',
    '11': 'UY',
    '12': 'AR',
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

    $('#id_account').change(function() {
        var country = currency_mapping[$(this).val()];
        $('#id_country').val(country);
    });

});
