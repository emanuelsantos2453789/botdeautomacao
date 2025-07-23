// frontend/script.js

document.addEventListener('DOMContentLoaded', () => {
    const navLinks = document.querySelectorAll('.main-nav a');
    const contentSections = document.querySelectorAll('.content-section');

    // Função para mostrar a seção correta
    const showSection = (sectionId) => {
        contentSections.forEach(section => {
            if (section.id === sectionId) {
                section.classList.remove('hidden');
                section.classList.add('active'); // Opcional, para indicar qual seção está ativa visualmente
            } else {
                section.classList.add('hidden');
                section.classList.remove('active');
            }
        });

        // Atualiza a classe 'active' nos links de navegação
        navLinks.forEach(link => {
            if (link.dataset.section === sectionId) {
                link.classList.add('active');
            } else {
                link.classList.remove('active');
            }
        });
    };

    // Adiciona evento de clique aos links de navegação
    navLinks.forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault(); // Impede o comportamento padrão do link
            const sectionId = e.target.dataset.section;
            showSection(sectionId);
        });
    });

    // Mostra a seção Dashboard por padrão ao carregar a página
    showSection('dashboard');
});

// Futuramente, a lógica do Pomodoro, Metas, etc., virá aqui
// Exemplo:
// const pomodoroTimerDisplay = document.querySelector('.timer-display');
// const startButton = document.querySelector('.pomodoro-controls .btn-primary');
// startButton.addEventListener('click', () => {
//     // Lógica para iniciar Pomodoro (comunicação com backend)
//     pomodoroTimerDisplay.textContent = "24:59"; // Apenas um exemplo visual
// });
