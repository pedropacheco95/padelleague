const tickets = document.querySelectorAll('.ticket');
const kanbanColumns = document.querySelectorAll('.kanban-column');

let selectedTicket;
let isTicketSelected = false;
let selectedKanbanColumn;

document.addEventListener('mousemove', function(e) {
    handleColumns(e)
});

document.addEventListener('touchmove', function(e) {
    handleColumns(e.touches[0])
});


// Add event listeners for drag and drop functionality
tickets.forEach(ticket => {
    ticket.addEventListener('mousedown', handleMouseDownTicket);
    ticket.addEventListener('touchstart', handleTouchStartTicket);

    ticket.addEventListener('mouseup', handleMouseUpTicket);
    ticket.addEventListener('touchend', handleTouchEndTicket);

    ticket.addEventListener('mousemove', handleMouseMoveTicket);
    ticket.addEventListener('touchmove', handleTouchMoveTicket);

    ticket.addEventListener('touchcancel', handleTouchCancelTicket);
});

/* // Add event listeners for drag and drop functionality
kanbanColumns.forEach(kanbnaColumn => {
    kanbnaColumn.addEventListener('mouseover', handleMouseOnColumn);
    kanbnaColumn.addEventListener('touchmove', handleTouchOnColumn);

    kanbnaColumn.addEventListener('mouseleave', handleMouseLeaveColumn);
    kanbnaColumn.addEventListener('touchend', handleTouchEndColumn);
}); */

// Drag and Drop event handlers

//Handle start dragging ticket both on desktop and mobile
function selectTicket(ele,e){
    ele.style.opacity = '0.4';
    selectedTicket = ele;
    isTicketSelected = true;
}

function handleMouseDownTicket(e) {
    selectTicket(this,e)
}

function handleTouchStartTicket(e) {
    selectTicket(this,e);
}

//Handle stop dragging ticket both on desktop and mobile

function stopDraggingTicket(ele){
    ele.style.opacity = '1';
    ele.style.position = '';
    ele.style.left = '';
    ele.style.top = '';
    ele.style.width = '';

    dropTicketOnColumn(selectedTicket,selectedKanbanColumn)
    selectedTicket = undefined;
    isTicketSelected = false;
}

function handleMouseUpTicket() {
    stopDraggingTicket(this);
}

function handleTouchEndTicket(e) {
    stopDraggingTicket(this);
}

//Handle moving ticket both on desktop and mobile

function moveTicket(e,touchLocation,ticket){
    e.preventDefault(); // Prevent scrolling when moving the ticket

    if (ticket) {
        const xOffset = touchLocation.clientX - ticket.offsetWidth / 2;
        const yOffset = touchLocation.clientY - ticket.offsetHeight / 2;

        ticket.style.position = 'fixed';
        ticket.style.left = `${xOffset}px`;
        ticket.style.top = `${yOffset}px`;
        ticket.style.width = '20rem';
    }
}

function handleMouseMoveTicket(e){
    const mouseLocation = {
        clientX: e.clientX,
        clientY: e.clientY
    };
    moveTicket(e,mouseLocation,selectedTicket);
}

function handleTouchMoveTicket(e) {
    const touchLocation = e.targetTouches[0];
    moveTicket(e,touchLocation,selectedTicket);
}

//Handle touch cancelled ticket both on mobile

function handleTouchCancelTicket(e) {
    this.style.opacity = '1';
    this.removeAttribute('touch-dragged');
    this.style.position = '';
    this.style.left = '';
    this.style.top = '';
    kanbanColumns.forEach(column => column.classList.remove('over'));
}

function dropTicketOnColumn(ticket,column){
    if (ticket && column){
        if (ticket) {
            column.querySelector('.ticket-list').classList.remove('over');
            column.querySelector('.ticket-list').appendChild(ticket);
            organizeChildrenByPriority(column.querySelector('.ticket-list'));
            kanbanColumns.forEach(kanbanColumn => {
                unselectColumn(kanbanColumn)
            })
        }
    }
}

//Handle ticket over the column

function selectColumn(ele){
    if (selectedTicket){
        selectedKanbanColumn = ele;
        ele.querySelector('.ticket-list').classList.add('over');
    }
}

function handleMouseOnColumn(){
    selectColumn(this);
}

function handleTouchOnColumn(){
    selectColumn(this);
}

//Handle ticket leaving the column

function unselectColumn(ele){
    selectedKanbanColumn = undefined;
    ele.querySelector('.ticket-list').classList.remove('over');
}

function handleColumns(e){
    kanbanColumns.forEach(kanbanColumn => {
        let rect = kanbanColumn.getBoundingClientRect();
        if (e.clientX >= rect.left && e.clientX <= rect.right &&
            e.clientY >= rect.top && e.clientY <= rect.bottom) {
                selectColumn(kanbanColumn)
        } else if (kanbanColumn == selectedKanbanColumn) {
            unselectColumn(kanbanColumn)
        }
    })
}

function handleTouchEndColumn(){
    unselectColumn(this);
}
