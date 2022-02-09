players_buttons = document.getElementsByClassName('eliminate_player')
players_eliminated = document.getElementById('players_eliminated')
match_results = document.getElementsByClassName('game_results')
match_inputs_array = document.getElementsByClassName('game_inputs')
match_inputs = {}
for (input of match_inputs_array){
    match_inputs[input.id] = input
}

for (let element of players_buttons){
    element.addEventListener('click',highlight);
}

for (let element of match_results){
    element.addEventListener('click',deleteContent);
}

let clicked = '';

function highlight(button_element){
    remove_class_from_all('selected_player_on_edit')
    remove_class_from_all('edit_player_in_match')

    if (button_element.currentTarget.id == 'player_button'){
        var button_name = button_element.currentTarget.getAttribute('value')
        if (!clicked | clicked != button_name){
            var name_box = button_name + '_name';
            var image_box = button_name + '_image';
            for (element of document.getElementsByName(name_box)){
                element.classList.add('selected_player_on_edit');
            }
            document.getElementById(image_box).classList.add('edit_player_in_match');
            clicked = button_name
        }
        else {
            remove_player(button_name)
            clicked = ''
        }
    }
}

function remove_player(button_name){
    var name_box = button_name + '_name';
    var image_box = button_name + '_image';
    for (element of document.getElementsByName(name_box)){
        element.classList.add('player_removed');
    }
    document.getElementById(image_box).classList.add('player_removed_image');
    var els = players_eliminated.value
    players_eliminated.value = els.concat(button_name,';')
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