document.addEventListener('onload', fillAllManyToManyOptions());

function HideAndShowOptions(element, n) {
    if (element.classList.contains('selectable')) {
        element.classList.remove('selectable')
    } else {
        element.classList.add('selectable')
    }
    var allOptions = element.parentNode.querySelectorAll('.options');
    var selectableSiblings = element.parentNode.querySelectorAll('.selectable');
    var siblings = Array.prototype.slice.call(selectableSiblings, 0, n);
    for (let sibling of allOptions) {
        if (siblings.includes(sibling)) {
            sibling.style.display = "inherit";
        } else {
            sibling.style.display = "none";
        }
    }
}

// Add a selected option to the select element and the selected options div
function addOption(option) {
    HideAndShowOptions(option, 3);
    let select_input_id = option.dataset.name;
    let option_value = option.dataset.value;
    const optionButton = document.createElement('div');
    const optionButtonBox = document.getElementById('selected_options_' + select_input_id);
    const select_input = document.getElementById(select_input_id);
    const optionsList = document.getElementById('options_list_' + select_input_id);
    const input = document.getElementById('text_input_select_' + select_input_id);
    
    optionButton.innerText = option.innerText;
    optionButton.classList.add('option_div');
    optionButton.classList.add('was_not_readonly_div');
    optionButtonBox.appendChild(optionButton);

    const closeSymbol = document.createElement('span');
    closeSymbol.innerHTML = '&times;';
    optionButton.appendChild(closeSymbol);
    
    optionButton.addEventListener('click', () => {
        optionButtonBox.removeChild(optionButton);
        setSelectOption(select_input, option_value, false);
        setFocus(false,select_input,optionButtonBox.parentNode)
        HideAndShowOptions(option, 3);
    });

    setSelectOption(select_input, option_value, true);

    input.value = '';
    optionsList.style.display = 'none';
}

function removeOption(optionButton) {
    let select_input_id = optionButton.dataset.name;
    let option_value = optionButton.dataset.value;
    let option = document.getElementById("option_" + option_value);
    const optionButtonBox = document.getElementById('selected_options_' + select_input_id);
    const select_input = document.getElementById(select_input_id);
    optionButtonBox.removeChild(optionButton);
    setSelectOption(select_input, option_value, false);
    HideAndShowOptions(option, 3);

    let id1 = window.location.pathname.split('/').slice(-1)[0];
    let id2 = option_value
    let field_name = select_input_id;
    let model_name1 = optionButton.dataset.model;
    let model_name2 = optionButton.dataset.related_model;

    fetch('/api/remove_relationship', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            model_name1: model_name1,
            model_name2: model_name2,
            field_name:field_name,
            id1: id1,
            id2: id2
        })
    })
}

function setSelectOption(select_input, option_value, selected) {
    if (selected){
        var newOption = document.createElement("option");
        newOption.text = option_value;
        newOption.value = option_value;
        select_input.appendChild(newOption);
        newOption.selected = selected;
    }
    else{
        for (let option of select_input.options) {
            if (option.value == option_value) {
                option.selected = selected;
                break;
            }
        }
    }
}

function showOptions(element){
    let select_input_id = element.dataset.name;
    if (!element.classList.contains('readonly_div')) {
        showHideElement('options_list_' + select_input_id)
    }
}

function searchOptions(input) {
    var filter = input.value.toUpperCase();
    var allOptions = input.parentNode.querySelectorAll('.options');
    let shown = 0;
    for (let option of allOptions) {
        // Only show 3 options at a time
        if (shown < 3 && option.classList.contains('selectable')) {       
            if (option.innerText.toUpperCase().indexOf(filter) > -1 ) {
                option.style.display = "inherit";
                shown++;
            } else {
                option.style.display = "none";
            }
        } else {
            option.style.display = "none";
        }
    }
}

function getAllOptions(ele){
    let model_name = ele.dataset.related_model;
    let many_to_many_values_inputed = document.getElementsByClassName('many_to_many_values_inputed');
    let values = Array.from(many_to_many_values_inputed).map(el => +el.dataset.value);
    $.getJSON(`/api/query/${model_name}` , function(data) {
        for (let option of data) {
            let option_text = option.name;
            let option_value = option.value;
            let show = !values.includes(option_value);
            let option_div = createManyToManyOption(ele.dataset.name,option_text,option_value,show);
            ele.insertBefore(option_div, ele.lastElementChild);
        }
    });
}

function fillAllManyToManyOptions(){
    let containers = document.getElementsByClassName('many_to_many_container');
    for (let container of containers) {
        let check = container.dataset.filled;
        if (check == 'false') {
            getAllOptions(container);
        }
        container.dataset.filled = 'true';
    }
}   

function createManyToManyOption(field_name,option_text,option_value,show){
    var div = document.createElement("div");
    div.setAttribute("id", "option_" + option_value)
    div.setAttribute("data-name", field_name);
    div.setAttribute("data-value", option_value);
    div.setAttribute("class", "options");
    if (show) {
        div.classList.add("selectable");
    } else {
        div.style.display = "none";
    }
    div.setAttribute("onclick", "addOption(this)");
    div.textContent = option_text;
    return div
}

function checkEmptyElement(element){
    if (element.children.length === 0) {
        return true;
    }
    return false;
}

function setFocusForManyToMany(element){
    let select_input_id = element.dataset.name;
    const optionButtonBox = document.getElementById('selected_options_' + select_input_id);
    const select_input = document.getElementById(select_input_id);
    if (checkEmptyElement(optionButtonBox)) {
        setFocus(false,select_input,optionButtonBox.parentNode)
    } else {
        setFocus(true,select_input,optionButtonBox.parentNode)
    }
}

async function addContentToModal(url,modal,modal_id,field_name) {
    const response = await fetch(url);
    const templateHTML = await response.text();
    //Create a new div element with the template HTML
    const template = document.createElement('div');
    template.setAttribute("class", "modal_content_from_url");
    template.innerHTML = templateHTML;
    modal.querySelector('.modal_body').innerHTML = '';
    modal.querySelector('.modal_body').appendChild(template);
    let confirmButton = modal.querySelector('#confirm_create_' + field_name);
    let form = modal.querySelector('form');
    confirmButton.addEventListener('click', function(){
        confirmBasicCreate(form,modal_id,field_name);
    });
}

async function confirmBasicCreate(form,modal_id,field_name){
    const response = await submitAndGetResponse(form);
    const options_list = document.getElementById('options_list_' + field_name);
    const optionButtonBox = document.getElementById('selected_options_' + field_name);
    let option_div = createManyToManyOption(field_name,response.name,response.value,true);
    options_list.insertBefore(option_div, options_list.lastElementChild);
    addOption(option_div);
    
    setFocusForManyToMany(optionButtonBox);
    let modal = document.getElementById(modal_id);
    modal.style.display = "none";
}

async function submitAndGetResponse(form){
    let url = form.action;
    let data = new FormData(form);
    const response = await fetch(url, {
        method: 'POST',
        body: data
    })

    const jsonResponse = await response.json();
    return jsonResponse;
}


function loadModal(element){
    let url = element.dataset.url;
    let title = element.dataset.title;
    let modal_id = element.dataset.modal_id;
    let field_name = element.dataset.field_name;
    let modal = createModal(title, modal_id, field_name);
    addContentToModal(url,modal,modal_id,field_name);
    element.parentNode.style.display = 'none';
    modal.style.display = "block";
}

function setHiddenFieldValue(element){
    let field_name = element.dataset.field_name;
    let hiddenInput = document.getElementById('hiddenInput_' + field_name);
    if (element.type === 'checkbox') {
        hiddenInput.value = element.checked;
    }
    else{
        hiddenInput.value = element.value;
    }
}

function turnToDateInput(element){
    if (!element.hasAttribute('readonly')){
        element.type = 'date';
    }
}

function turnToDateTimeInput(element){
    if (!element.hasAttribute('readonly')){
        element.type = 'datetime-local';
    }
} 

function turnToTextInput(element){
    if (element.value === '') {
        element.type = 'text';
    }
}

