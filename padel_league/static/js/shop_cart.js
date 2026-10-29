function deleteOrderLine(ele){
    let url = api_url.replace(/.$/, '') + ele.getAttribute('data-orderline_id');
    $.post(url);
    let row = ele.parentElement.parentElement
    row.parentNode.removeChild(row);
}
