let players_buttons = document.getElementsByClassName('choose_player')
let modal_player_buttons = document.getElementsByClassName('choose_player_line');
let match_results = document.getElementsByClassName('game_results')
let match_inputs_array = document.getElementsByClassName('game_inputs')
let modalButton = document.getElementById("modalActivation");
let match_inputs = {}
for (input of match_inputs_array){
    match_inputs[input.id] = input
}

for (let element of players_buttons){
    element.addEventListener('click',highlight);
}

for (let element of match_results){
    element.addEventListener('click',deleteContent);
}

for (let element of modal_player_buttons){
    element.addEventListener('click',select_player);
}
let clicked = '';

function highlight(button_element){
    modalButton.click();
    remove_class_from_all('selected_player_on_edit')
    remove_class_from_all('edit_player_in_match')

    if (button_element.currentTarget.id == 'player_button'){
        var button_name = button_element.currentTarget.getAttribute('value')
        if (!clicked | clicked != button_name){
            var name_box = button_name + '_name';
            for (element of document.getElementsByName(name_box)){
                element.classList.add('selected_player_on_edit');
            }
            clicked = button_name
        }
    }
}

function remove_highlight(){
    for (element of document.getElementsByClassName('selected_player_on_edit')){
        element.classList.remove('selected_player_on_edit');
    }
}

function remove_class_from_all(class_name){
    let elements = document.getElementsByClassName(class_name);
    while(elements.length > 0){
        elements[0].classList.remove(class_name);
    }
}

function copyToInput(){
    for (let element of match_results){
        var element_name = element.getAttribute('value');
        var input = match_inputs[element_name + '_input'];

        input.value = parseInt(element.innerHTML.replace('&nbsp;','').trim())
    }
}

function deleteContent(element){
    element.currentTarget.innerHTML = '';
}

function select_player(element){
    let player_id = element.currentTarget.getAttribute('data-player_id');
    let player_name = element.currentTarget.getAttribute('data-player_name');
    let player_image = element.currentTarget.getAttribute('data-player_image');
    let name_box = clicked + '_name';
    let image_box = clicked + '_image';
    let input_box = clicked + '_id';
    for (element of document.getElementsByName(name_box)){
        element.innerHTML = player_name;
    }
    document.getElementById(image_box).style.backgroundImage = `url('${player_image}')`;
    document.getElementById(input_box).value = player_id;
    modal.style.display = "none";
}

function check_inputs(){
    let inputs = document.getElementsByTagName('input');
    for (let input of inputs){
        if (input.value == ''){
            console.log(input)
            let flash = document.createElement('div');
            flash.innerHTML = 'Por favor preecnche todos os campos (Data,resultado, e todos os jogadores)';
            flash.classList.add('alert');
            flash.classList.add('alert-danger');
            flash.classList.add('border');
            flash.classList.add('text-center');
            flash.setAttribute('role', 'alert')
            nav = document.getElementById('main-nav');
            nav.parentNode.insertBefore(flash, nav.nextSibling);
            return false;
        }
    }
    return true;
}
