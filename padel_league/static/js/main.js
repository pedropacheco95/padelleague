window.addEventListener('load',(event)=>{
    $('html, body').animate({
        scrollTop: $('#site-container').offset().top
    }, 'slow');
});