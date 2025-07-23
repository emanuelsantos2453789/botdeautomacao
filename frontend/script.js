// frontend/script.js

document.addEventListener('DOMContentLoaded', () => {
    // --- Seletores de Elementos ---
    const navItems = document.querySelectorAll('.bottom-nav .nav-item');
    const contentSections = document.querySelectorAll('.content-section');
    const appMainPanel = document.querySelector('.app-main-panel');
    const backgroundGradientAnimated = document.querySelector('.background-gradient-animated'); // Para o fundo animado

    // --- Mapeamento de Temas (Cores e Gradientes de Fundo) ---
    // Estas cores serão aplicadas dinamicamente via variáveis CSS no app-main-panel
    // E o gradiente de fundo no body também mudará
    const sectionThemes = {
        'dashboard': {
            primary: '#00FFFF', secondary: '#00FF99', // Neon Blue, Neon Green
            bgGradient: 'radial-gradient(circle at 10% 20%, #000428, #004e92)', // Azul Escuro Cósmico
        },
        'pomodoro': {
            primary: '#FF8C00', secondary: '#FF00FF', // Neon Orange, Neon Pink
            bgGradient: 'radial-gradient(circle at 90% 80%, #1A2980, #203A43)', // Roxos e Azuis Sombrios
        },
        'metas': {
            primary: '#9900FF', secondary: '#FF00FF', // Neon Purple, Neon Pink
            bgGradient: 'linear-gradient(135deg, #1C0F2B 0%, #3A0C4D 100%)', // Púrpura Profundo
        },
        'agenda': {
            primary: '#ADD8E6', secondary: '#87CEFA', // Azul Claro
            bgGradient: 'linear-gradient(135deg, #0F2027 0%, #203A43 50%, #2C5364 100%)', // Tons de Azul Oceano
        },
        'rotinas': {
            primary: '#90EE90', secondary: '#32CD32', // Verde Vivo
            bgGradient: 'linear-gradient(135deg, #0A2E0A 0%, #1E561E 100%)', // Verdes da Natureza Profunda
        },
        'relatorios': {
            primary: '#D3D3D3', secondary: '#A9A9A9', // Cinza Metálico
            bgGradient: 'linear-gradient(135deg, #1C1C1C 0%, #424242 100%)', // Cinza Técnico
        },
        'configuracoes': {
            primary: '#FFA500', secondary: '#FFD700', // Dourado/Laranja
            bgGradient: 'linear-gradient(135deg, #303030 0%, #505050 100%)', // Cinza Robusto
        },
    };

    /**
     * Alterna a visibilidade das seções, aplica o tema de cor e atualiza o fundo animado.
     * @param {string} sectionId O ID da seção a ser exibida.
     */
    const showSection = (sectionId) => {
        // Remove 'active' e adiciona 'hidden' a todas as seções para transição suave
        contentSections.forEach(section => {
            section.classList.remove('active');
            section.classList.add('hidden');
        });

        // Adiciona 'active' à seção desejada após um pequeno delay para a animação de saída
        const targetSection = document.getElementById(sectionId);
        if (targetSection) {
            setTimeout(() => {
                targetSection.classList.remove('hidden');
                targetSection.classList.add('active'); // CSS fará o fade-in e slide-up
            }, 50); // Pequeno delay para a animação da seção anterior
        }

        // Atualiza a classe 'active' na barra de navegação
        navItems.forEach(item => {
            item.classList.remove('active');
            if (item.dataset.section === sectionId) {
                item.classList.add('active');
            }
        });

        // Aplica as variáveis CSS de cor do tema e muda o gradiente de fundo principal
        const currentTheme = sectionThemes[sectionId];
        if (currentTheme) {
            appMainPanel.style.setProperty('--theme-primary', currentTheme.primary);
            appMainPanel.style.setProperty('--theme-secondary', currentTheme.secondary);
            // Define o background do gradiente animado
            backgroundGradientAnimated.style.background = currentTheme.bgGradient;
        }
    };

    // Adiciona event listeners aos itens da navegação
    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const sectionId = item.dataset.section;
            showSection(sectionId);
        });
    });

    // --- Lógica do Pomodoro Aprimorada com SVG ---
    const timerDisplay = document.querySelector('#pomodoro .time-value');
    const timerStatus = document.querySelector('#pomodoro .timer-status');
    const startButton = document.querySelector('#pomodoro .btn-start');
    const pauseButton = document.querySelector('#pomodoro .btn-pause');
    const resetButton = document.querySelector('#pomodoro .btn-reset');
    const skipButton = document.querySelector('#pomodoro .btn-skip');
    const timerCircleProgress = document.querySelector('.timer-circle-progress'); // O círculo de progresso SVG

    let timerInterval; // Variável para o setInterval
    let timeLeft; // Tempo restante em segundos
    let isPaused = true;
    let isFocusMode = true; // true para Foco, false para Descanso

    // Duração dos ciclos em segundos
    const FOCUS_TIME = 25 * 60; // 25 minutos
    const SHORT_BREAK_TIME = 5 * 60; // 5 minutos
    const LONG_BREAK_TIME = 15 * 60; // 15 minutos (para ciclos futuros)
    let totalTimeForCurrentMode = FOCUS_TIME; // Tempo total para o modo atual

    /**
     * Atualiza o display do timer e o progresso do SVG.
     */
    function updateTimerDisplay() {
        const minutes = Math.floor(timeLeft / 60);
        const seconds = timeLeft % 60;
        timerDisplay.textContent = `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;

        // Atualiza o círculo de progresso SVG
        const radius = timerCircleProgress.r.baseVal.value;
        const circumference = radius * 2 * Math.PI;
        const offset = circumference - (timeLeft / totalTimeForCurrentMode) * circumference;

        timerCircleProgress.style.strokeDasharray = `${circumference} ${circumference}`;
        timerCircleProgress.style.strokeDashoffset = offset;

        // Animação de brilho no texto do timer quando o tempo está acabando
        if (timeLeft < 60 && timeLeft % 2 === 0 && !isPaused) { // Menos de 1 minuto
             timerDisplay.classList.add('time-critical');
        } else {
             timerDisplay.classList.remove('time-critical');
        }
    }

    /**
     * Inicia ou resume o timer.
     */
    function startTimer() {
        if (!isPaused) return; // Só inicia se estiver pausado

        isPaused = false;
        timerStatus.textContent = isFocusMode ? 'Foco Ativo ⚡' : 'Pausa Ativa 🧘';
        timerStatus.classList.add('pulsing-text'); // Ativa a animação de pulso no status

        // Garante que o brilho do anel de progresso esteja ativo
        timerCircleProgress.classList.add('active-glow');

        timerInterval = setInterval(() => {
            if (timeLeft <= 0) {
                clearInterval(timerInterval);
                isPaused = true;
                timerStatus.classList.remove('pulsing-text'); // Desativa a animação de pulso

                // Toca um som de notificação (você pode adicionar um elemento <audio> no HTML)
                const audio = new Audio('path/to/your/notification.mp3'); // Mude o caminho
                audio.play().catch(e => console.error("Erro ao tocar áudio:", e));

                // Transição para o próximo modo
                if (isFocusMode) {
                    timeLeft = SHORT_BREAK_TIME;
                    totalTimeForCurrentMode = SHORT_BREAK_TIME;
                    isFocusMode = false;
                    timerStatus.textContent = 'Pausa Iniciada 🎉';
                } else {
                    timeLeft = FOCUS_TIME;
                    totalTimeForCurrentMode = FOCUS_TIME;
                    isFocusMode = true;
                    timerStatus.textContent = 'Foco Reiniciado 🚀';
                }
                updateTimerDisplay();
                startTimer(); // Inicia o próximo ciclo automaticamente
            } else {
                timeLeft--;
                updateTimerDisplay();
            }
        }, 1000); // Atualiza a cada segundo
    }

    /**
     * Pausa o timer.
     */
    function pauseTimer() {
        clearInterval(timerInterval);
        isPaused = true;
        timerStatus.textContent = isFocusMode ? 'Foco Pausado ⏸️' : 'Pausa Pausada 💤';
        timerStatus.classList.remove('pulsing-text'); // Desativa a animação de pulso
        timerCircleProgress.classList.remove('active-glow'); // Remove o brilho do anel
        timerDisplay.classList.remove('time-critical'); // Remove brilho crítico do tempo
    }

    /**
     * Redefine o timer para o início do modo de foco.
     */
    function resetTimer() {
        clearInterval(timerInterval);
        isPaused = true;
        timeLeft = FOCUS_TIME;
        totalTimeForCurrentMode = FOCUS_TIME;
        isFocusMode = true;
        updateTimerDisplay();
        timerStatus.textContent = 'Pronto para Ativar';
        timerStatus.classList.remove('pulsing-text');
        timerCircleProgress.classList.remove('active-glow');
        timerDisplay.classList.remove('time-critical');
    }

    /**
     * Pula para o próximo modo (foco ou descanso).
     */
    function skipTimer() {
        clearInterval(timerInterval);
        isPaused = true;
        timerStatus.classList.remove('pulsing-text');
        timerCircleProgress.classList.remove('active-glow');
        timerDisplay.classList.remove('time-critical');

        if (isFocusMode) {
            timeLeft = SHORT_BREAK_TIME;
            totalTimeForCurrentMode = SHORT_BREAK_TIME;
            isFocusMode = false;
            timerStatus.textContent = 'Pausa Forçada ⏭️';
        } else {
            timeLeft = FOCUS_TIME;
            totalTimeForCurrentMode = FOCUS_TIME;
            isFocusMode = true;
            timerStatus.textContent = 'Retomando Foco 🚀';
        }
        updateTimerDisplay();
        startTimer(); // Inicia o próximo ciclo automaticamente
    }

    // Adiciona event listeners aos botões do Pomodoro
    if (startButton) startButton.addEventListener('click', startTimer);
    if (pauseButton) pauseButton.addEventListener('click', pauseTimer);
    if (resetButton) resetButton.addEventListener('click', resetTimer);
    if (skipButton) skipButton.addEventListener('click', skipTimer);

    // --- Inicialização ---
    // Define o tempo inicial para o Pomodoro e atualiza o display
    timeLeft = FOCUS_TIME;
    updateTimerDisplay();

    // Exibe a seção Dashboard por padrão ao carregar a página
    showSection('dashboard');
});
