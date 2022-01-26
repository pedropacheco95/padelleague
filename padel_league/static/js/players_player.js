document.getElementById('personal_data_button').addEventListener('click',activateDataTabs);
document.getElementById('sports_data_button').addEventListener('click',activateDataTabs);

function activateDataTabs(button_element){
    for (element of document.getElementsByClassName('c-player__item--active')){
        element.classList.remove('c-player__item--active');
    }
    for (element of document.getElementsByClassName('c-player__data-list--is-visible')){
        element.classList.remove('c-player__data-list--is-visible');
    }

    button_element.currentTarget.parentNode.classList.add('c-player__item--active');
    if (button_element.currentTarget.id == 'personal_data_button'){
        document.getElementById('personal_data_tab').classList.add('c-player__data-list--is-visible');
    }
    if (button_element.currentTarget.id == 'sports_data_button'){
        document.getElementById('sports_data_tab').classList.add('c-player__data-list--is-visible');
    }
}