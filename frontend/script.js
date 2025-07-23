// frontend/script.js

document.addEventListener('DOMContentLoaded', () => {
    // Seleciona todos os links da nova barra de navegação inferior
    const navItems = document.querySelectorAll('.bottom-nav .nav-item');
    // Seleciona todas as seções de conteúdo
    const contentSections = document.querySelectorAll('.content-section');
    // Seleciona o painel principal, onde o tema de cor será aplicado
    const appMainPanel = document.querySelector('.app-main-panel');
    // Seleciona a div de animação de fundo para possíveis futuras interações
    const backgroundAnimationLayer = document.querySelector('.background-animation-layer');

    // Mapeamento de IDs de seção para suas cores primárias e secundárias neon
    // Essas cores serão aplicadas dinamicamente via variáveis CSS no app-main-panel
    const sectionThemes = {
        'dashboard': { primary: '#00FFFF', secondary: '#00FF99' }, // Neon Blue, Neon Green
        'pomodoro': { primary: '#FF8C00', secondary: '#FF00FF' },   // Neon Orange, Neon Pink
        'metas': { primary: '#9900FF', secondary: '#FF00FF' },      // Neon Purple, Neon Pink
        'agenda': { primary: '#ADD8E6', secondary: '#87CEFA' },     // Azul Claro
        'rotinas': { primary: '#90EE90', secondary: '#32CD32' },    // Verde Vivo
        'relatorios': { primary: '#D3D3D3', secondary: '#A9A9A9' }, // Cinza Metálico
        'configuracoes': { primary: '#FFA500', secondary: '#FFD700' }, // Dourado/Laranja
    };

    /**
     * Alterna a visibilidade das seções e aplica o tema de cor correspondente.
     * @param {string} sectionId O ID da seção a ser exibida (ex: 'dashboard', 'pomodoro').
     */
    const showSection = (sectionId) => {
        // Esconde todas as seções e remove a classe 'active'
        contentSections.forEach(section => {
            section.classList.remove('active');
            section.classList.add('hidden'); // Garante que a seção esteja oculta
        });

        // Mostra a seção desejada e adiciona a classe 'active'
        const targetSection = document.getElementById(sectionId);
        if (targetSection) {
            targetSection.classList.remove('hidden');
            targetSection.classList.add('active'); // Animação de entrada via CSS
        }

        // Atualiza a classe 'active' na barra de navegação inferior
        navItems.forEach(item => {
            item.classList.remove('active');
            if (item.dataset.section === sectionId) {
                item.classList.add('active');
            }
        });

        // Aplica as variáveis CSS de cor do tema da seção ao app-main-panel
        const currentTheme = sectionThemes[sectionId];
        if (currentTheme) {
            appMainPanel.style.setProperty('--theme-primary', currentTheme.primary);
            appMainPanel.style.setProperty('--theme-secondary', currentTheme.secondary);
            // Também podemos mudar a animação de fundo do body aqui para corresponder ao tema principal
            document.body.style.background = `var(--bg-${sectionId})`;
        }
    };

    // Adiciona o event listener de clique a cada item da navegação inferior
    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault(); // Previne o comportamento padrão do link
            const sectionId = item.dataset.section; // Obtém o ID da seção do atributo data-section
            showSection(sectionId);
        });
    });

    // --- Lógica do Pomodoro (Exemplo Básico) ---
    const timeValue = document.querySelector('#pomodoro .time-value');
    const timerStatus = document.querySelector('#pomodoro .timer-status');
    const startButton = document.querySelector('#pomodoro .btn-start');
    const pauseButton = document.querySelector('#pomodoro .btn-pause');
    const resetButton = document.querySelector('#pomodoro .btn-reset');
    const skipButton = document.querySelector('#pomodoro .btn-skip');

    let timer;
    let timeLeft = 25 * 60; // 25 minutos em segundos
    let isPaused = true;
    let isFocusMode = true; // True para foco, false para descanso

    function updateTimerDisplay() {
        const minutes = Math.floor(timeLeft / 60);
        const seconds = timeLeft % 60;
        timeValue.textContent = `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
    }

    function startTimer() {
        if (!isPaused) return; // Só inicia se estiver pausado
        isPaused = false;
        timerStatus.textContent = isFocusMode ? 'Foco Ativo' : 'Pausa Relaxante';
        // Atualiza o brilho do texto de status com base no modo
        timerStatus.style.color = isFocusMode ? 'var(--neon-green)' : 'var(--neon-blue)';
        timerStatus.style.textShadow = isFocusMode ? '0 0 10px var(--neon-green)' : '0 0 10px var(--neon-blue)';


        timer = setInterval(() => {
            if (timeLeft <= 0) {
                clearInterval(timer);
                isPaused = true;
                // Toca um som (pode ser um <audio> element no HTML)
                alert('Tempo esgotado!'); // Substitua por algo mais elegante
                if (isFocusMode) {
                    timeLeft = 5 * 60; // 5 minutos de descanso
                    isFocusMode = false;
                } else {
                    timeLeft = 25 * 60; // Volta para 25 minutos de foco
                    isFocusMode = true;
                }
                updateTimerDisplay();
                startTimer(); // Inicia o próximo ciclo automaticamente
            } else {
                timeLeft--;
                updateTimerDisplay();
            }
        }, 1000);
    }

    function pauseTimer() {
        clearInterval(timer);
        isPaused = true;
        timerStatus.textContent = isFocusMode ? 'Foco Pausado' : 'Pausa Pausada';
    }

    function resetTimer() {
        clearInterval(timer);
        isPaused = true;
        timeLeft = 25 * 60;
        isFocusMode = true;
        updateTimerDisplay();
        timerStatus.textContent = 'Pronto para Focar';
    }

    function skipTimer() {
        clearInterval(timer);
        isPaused = true;
        if (isFocusMode) {
            timeLeft = 5 * 60; // Pula para o descanso
            isFocusMode = false;
        } else {
            timeLeft = 25 * 60; // Pula para o foco
            isFocusMode = true;
        }
        updateTimerDisplay();
        timerStatus.textContent = 'Próximo Ciclo';
        // Inicia automaticamente o próximo segmento após pular
        startTimer();
    }


    // Adiciona event listeners aos botões do Pomodoro
    if(startButton) startButton.addEventListener('click', startTimer);
    if(pauseButton) pauseButton.addEventListener('click', pauseTimer);
    if(resetButton) resetButton.addEventListener('click', resetTimer);
    if(skipButton) skipButton.addEventListener('click', skipTimer);

    // Inicializa o display do timer na carga da página
    updateTimerDisplay();


    // Exibe a seção Dashboard por padrão ao carregar a página
    showSection('dashboard');
});
