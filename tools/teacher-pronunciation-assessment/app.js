(function () {
  const MAX_ATTEMPTS = 3;
  const STORAGE_KEY = "accentScreeningState.v1";
  const QUESTION_KEY = "accentScreeningQuestions.v3";
  const DB_NAME = "accentScreeningVideos";
  const DB_STORE = "videos";

  const LANGUAGES = {
    cantonese: {
      label: "香港粵語",
      short: "粵語",
      locale: "zh-HK",
      description: "香港繁體字固定朗讀，評估粵語發音與流利度。",
      mode: "read"
    },
    taiwan_mandarin: {
      label: "臺灣腔國語",
      short: "臺灣國語",
      locale: "zh-TW",
      description: "臺灣繁體字固定朗讀，評估臺灣腔國語。",
      mode: "read"
    },
    english: {
      label: "英语教学表达",
      short: "英语",
      locale: "en-US",
      description: "中文教学场景提示，候选人需用英语自然表达。",
      mode: "scenario"
    }
  };

  const DEFAULT_QUESTIONS = [
    ["cantonese", "課前招呼", "基礎", "各位同學早晨，今日我哋會一齊練習新嘅生字同句式。請大家準備好課本同鉛筆，留心聽老師示範。等陣我會請幾位同學試吓讀出嚟，如果讀錯都唔緊要，最重要係夠膽開口同慢慢改善。"],
    ["cantonese", "課堂規則", "標準", "上堂嘅時候，請大家保持安靜，有問題可以舉手問。老師講解完之後，我哋會分組練習，大家要互相幫忙，亦要尊重其他同學嘅答案。輪到你發言時，請用完整句子清楚表達自己嘅諗法。"],
    ["cantonese", "閱讀引導", "標準", "請大家先睇第一段，留意主角講咗啲乜嘢，同埋佢當時可能有咩感受。讀完之後，諗一諗呢段說話想表達邊一種心情。等陣分享答案時，可以引用文中一個詞語嚟支持你嘅睇法。"],
    ["cantonese", "發音糾正", "進階", "呢個字嘅聲調要再清楚啲，唔好讀得太急。你可以先聽老師示範一次，再跟住慢慢讀。讀嘅時候留意口形同停頓，如果第一遍未準確都冇問題，我哋再試多一次，直到聲音更加自然。"],
    ["cantonese", "課堂鼓勵", "基礎", "你今次讀得好好，比頭先更加自然，而且停頓都清楚咗。下一次可以試吓講完整句，將原因一齊講出嚟，咁樣表達會更加清楚。老師見到你有進步，希望你繼續保持，勇敢啲開口練習。"],
    ["cantonese", "互動提問", "標準", "如果你係故事入面嘅小朋友，你會點樣回答老師呢？請你先諗十秒鐘，再用一句完整嘅說話同大家分享。回答時可以講出你嘅選擇、原因同感受，唔使怕答案同其他同學唔一樣。"],
    ["cantonese", "活動安排", "標準", "等陣我哋會做一個小遊戲，每組有兩分鐘時間討論，然後派一位同學出嚟回答問題。討論時請每個人都講一句意見，記低最重要嘅答案。時間到之後，老師會請大家安靜聽其他組分享。"],
    ["cantonese", "作業說明", "基礎", "今日嘅功課係完成工作紙第一至第三題，記得寫清楚姓名同日期。第一題要圈出生字，第二題要寫完整句子，第三題要用自己嘅說話回答。聽日上堂之前交畀老師，有唔明可以早啲問。"],
    ["cantonese", "課堂提醒", "進階", "大家答問題嘅時候，可以先諗清楚重點，再用自己嘅說話講出嚟，唔需要完全照住書讀。如果你想補充同學嘅答案，請先舉手，然後有禮貌咁講出新嘅想法，令討論更加完整。"],
    ["cantonese", "結課總結", "標準", "今日我哋學咗三個新詞語，亦練習咗用完整句回答問題。大家表現得好投入，尤其係分組討論嗰陣，好多同學都願意分享。返屋企之後，記得再朗讀一次課文，聽日我哋會做小測驗。"],
    ["taiwan_mandarin", "課前招呼", "基礎", "各位同學早安，今天我們會一起練習新的詞語和句型。請大家把課本和鉛筆準備好，先安靜聽老師示範。等一下我會請幾位同學唸給大家聽，唸錯也沒關係，重點是願意開口練習。"],
    ["taiwan_mandarin", "課堂規則", "標準", "上課的時候，請大家先保持安靜。如果有問題，可以舉手發問。老師說明完以後，我們會分組練習，請大家互相幫忙，也要尊重同學的回答。輪到你發言時，請用完整句說清楚。"],
    ["taiwan_mandarin", "閱讀引導", "標準", "請大家先看第一段，注意主角說了什麼，也想一想他當時可能有什麼感受。看完以後，請判斷這段話想表達哪一種心情。等一下分享答案時，可以引用課文裡的一個詞來說明。"],
    ["taiwan_mandarin", "發音糾正", "進階", "這個字的聲調可以再清楚一點，不要唸得太快。你可以先聽老師示範一次，再跟著慢慢唸。唸的時候注意嘴型和停頓，如果第一次不夠準也沒關係，我們再試一次就會更自然。"],
    ["taiwan_mandarin", "課堂鼓勵", "基礎", "你這次唸得很好，比剛剛更自然，而且停頓也更清楚。下一次可以試著說完整句，把原因一起說出來，這樣表達會更完整。老師看得到你的進步，請繼續保持，勇敢開口練習。"],
    ["taiwan_mandarin", "互動提問", "標準", "如果你是故事裡的小朋友，你會怎麼回答老師呢？請你先想十秒鐘，再用一句完整的話跟大家分享。回答時可以說出你的選擇、原因和感受，不需要擔心答案跟別人不一樣。"],
    ["taiwan_mandarin", "活動安排", "標準", "等一下我們會做一個小活動，每一組有兩分鐘可以討論，然後派一位同學上台回答問題。討論時請每個人都說一句想法，並把重點記下來。時間到以後，請安靜聽其他組分享。"],
    ["taiwan_mandarin", "作業說明", "基礎", "今天的作業是完成學習單第一題到第三題，記得寫上姓名和日期。第一題要圈出新詞，第二題要寫完整句，第三題要用自己的話回答。明天上課以前交給老師，有問題可以先問。"],
    ["taiwan_mandarin", "課堂提醒", "進階", "大家回答問題的時候，可以先想清楚重點，再用自己的話說出來，不需要完全照著課本唸。如果你想補充同學的答案，請先舉手，然後有禮貌地說出新的想法，讓討論更完整。"],
    ["taiwan_mandarin", "結課總結", "標準", "今天我們學了三個新詞語，也練習了用完整句回答問題。大家上課很投入，尤其分組討論時，很多同學都願意分享。回家以後，記得再朗讀一次課文，下一堂課我們會做小測驗。"],
    ["english", "课前自我介绍", "基础", "请用英语向学生做课前自我介绍，包含你的名字、今天的课程主题、学生需要准备的物品，以及你希望学生如何参与课堂。语气要亲切自然，像真正站在教室前开始一堂英文课。"],
    ["english", "课堂规则", "标准", "请用英语向学生说明上课要求：保持安静、需要发言时举手、尊重同学的回答、轮到小组活动时要合作。请用清楚但不严厉的语气，让学生知道规则是为了帮助大家学习。"],
    ["english", "引导回答", "标准", "请用英语鼓励一位害羞的学生回答问题。你需要先安抚他不要紧张，再给他一个简单的句型开头，最后邀请他试着说完整句。语气要温和、有耐心，像在真实课堂中互动。"],
    ["english", "发音纠正", "进阶", "请用英语纠正学生的一个发音错误。请先肯定学生愿意开口，再指出需要调整的声音，接着示范正确读法，最后请学生跟读一次。整段话要自然，不要让学生觉得被批评。"],
    ["english", "小组活动", "标准", "请用英语安排一个两人小组活动，说明活动时间、任务内容、每位学生要说几句话，以及完成后要分享答案。请让指令简洁清楚，确保学生听完就知道下一步要做什么。"],
    ["english", "阅读提问", "标准", "请用英语引导学生阅读一段故事，先提醒他们注意主角的行动和心情，再提出一个关于原因的问题。请鼓励学生用课文中的线索回答，而不是只说 yes 或 no。"],
    ["english", "课堂鼓励", "基础", "请用英语表扬学生刚才的回答，指出他做得好的地方，例如声音清楚或句子完整，并鼓励他下次加入更多原因。语气要真诚具体，让学生知道自己哪里进步了。"],
    ["english", "听力任务", "进阶", "请用英语说明一个听力练习：学生需要先听一段对话，再写下两个关键信息，最后和同桌核对答案。请提醒学生第一次先抓大意，第二次再注意细节，不要急着逐字翻译。"],
    ["english", "作业说明", "基础", "请用英语向学生说明今天的作业，包括要完成的页数、提交时间、遇到问题可以怎么做，以及下次课会如何检查。请让语气清楚友善，像老师在下课前提醒全班学生。"],
    ["english", "结课总结", "标准", "请用英语做一段简短的结课总结，回顾今天学到的词语、句型和课堂活动，并提醒学生下次课前要准备什么。最后请用一句鼓励的话结束，让学生有信心继续练习。"]
  ].map(([language, scene, difficulty, text], index) => ({
    id: `q_${language}_${index + 1}`,
    language,
    scene,
    difficulty,
    text: ensurePromptLength(language, text),
    enabled: true,
    version: 1,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString()
  }));

  function ensurePromptLength(language, text) {
    const endings = {
      cantonese: "讀嘅時候請保持自然語速，留意聲調、停頓同情緒，最後用清楚嘅聲音完成整段話。",
      taiwan_mandarin: "朗讀時請保持自然語速，注意聲調、停頓和情緒，最後用清楚穩定的聲音完成整段話。",
      english: "回答时请保持自然语速，注意英文发音、停顿和课堂语气，最后用清楚完整的方式结束这段说明。"
    };
    return text.length >= 96 ? text : `${text}${endings[language]}`;
  }

  const state = loadState();
  let questions = loadQuestions();
  let mediaStream = null;
  let recorder = null;
  let chunks = [];
  let activeLanguage = null;
  let activeStartedAt = null;

  const els = {
    tabs: document.querySelectorAll(".tab"),
    views: document.querySelectorAll(".view"),
    languageChoices: document.getElementById("languageChoices"),
    candidateName: document.getElementById("candidateName"),
    candidateRole: document.getElementById("candidateRole"),
    startAssessment: document.getElementById("startAssessment"),
    candidateHint: document.getElementById("candidateHint"),
    resetCandidate: document.getElementById("resetCandidate"),
    testCards: document.getElementById("testCards"),
    reportSummary: document.getElementById("reportSummary"),
    reports: document.getElementById("reports"),
    clearReports: document.getElementById("clearReports"),
    questionLanguage: document.getElementById("questionLanguage"),
    questionDifficulty: document.getElementById("questionDifficulty"),
    questionScene: document.getElementById("questionScene"),
    questionText: document.getElementById("questionText"),
    editingQuestionId: document.getElementById("editingQuestionId"),
    questionForm: document.getElementById("questionForm"),
    cancelEdit: document.getElementById("cancelEdit"),
    questionBank: document.getElementById("questionBank")
  };

  function loadState() {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) return JSON.parse(saved);
    return {
      currentCandidateId: createId("candidate"),
      candidates: {},
      tests: {}
    };
  }

  function saveState() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }

  function loadQuestions() {
    const saved = localStorage.getItem(QUESTION_KEY);
    if (saved) return JSON.parse(saved);
    localStorage.setItem(QUESTION_KEY, JSON.stringify(DEFAULT_QUESTIONS));
    return DEFAULT_QUESTIONS;
  }

  function saveQuestions() {
    localStorage.setItem(QUESTION_KEY, JSON.stringify(questions));
  }

  function createId(prefix) {
    return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
  }

  function init() {
    startFreshCandidate();
    renderLanguageChoices();
    renderQuestionLanguageOptions();
    bindEvents();
    hydrateCandidateInputs();
    renderAll();
  }

  function ensureCandidate() {
    if (!state.candidates[state.currentCandidateId]) {
      state.candidates[state.currentCandidateId] = {
        id: state.currentCandidateId,
        name: "",
        role: "",
        createdAt: new Date().toISOString()
      };
      saveState();
    }
  }

  function hydrateCandidateInputs() {
    const candidate = state.candidates[state.currentCandidateId];
    els.candidateName.value = candidate.name || "";
    els.candidateRole.value = candidate.role || "";
  }

  function bindEvents() {
    els.tabs.forEach((tab) => {
      tab.addEventListener("click", () => switchView(tab.dataset.view));
    });

    els.candidateName.addEventListener("input", updateCandidate);
    els.candidateRole.addEventListener("input", updateCandidate);
    els.startAssessment.addEventListener("click", startAssessment);
    els.resetCandidate.addEventListener("click", resetCandidate);
    els.clearReports.addEventListener("click", clearReports);
    els.questionForm.addEventListener("submit", saveQuestionFromForm);
    els.cancelEdit.addEventListener("click", clearQuestionForm);
  }

  function switchView(view) {
    els.tabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.view === view));
    els.views.forEach((panel) => panel.classList.toggle("active", panel.id === view));
    renderAll();
  }

  function updateCandidate() {
    const candidate = state.candidates[state.currentCandidateId];
    candidate.name = els.candidateName.value.trim();
    candidate.role = els.candidateRole.value.trim();
    saveState();
    renderReports();
  }

  function renderLanguageChoices() {
    els.languageChoices.innerHTML = "";
    const template = document.getElementById("languageChoiceTemplate");
    Object.entries(LANGUAGES).forEach(([key, lang]) => {
      const node = template.content.firstElementChild.cloneNode(true);
      node.querySelector("input").value = key;
      node.querySelector(".badge").textContent = lang.locale;
      node.querySelector("strong").textContent = lang.label;
      node.querySelector("small").textContent = lang.description;
      els.languageChoices.appendChild(node);
    });
  }

  function renderQuestionLanguageOptions() {
    els.questionLanguage.innerHTML = Object.entries(LANGUAGES)
      .map(([key, lang]) => `<option value="${key}">${lang.label}</option>`)
      .join("");
  }

  function startAssessment() {
    updateCandidate();
    const selected = [...els.languageChoices.querySelectorAll("input:checked")].map((input) => input.value);
    if (!selected.length) {
      setHint("请至少选择一种语种。", true);
      return;
    }

    selected.forEach((language) => ensureTestForLanguage(language));
    saveState();
    setHint("测评已创建。每个语种最多录制 3 次，重录不换题。");
    renderTests();
  }

  function ensureTestForLanguage(language) {
    const testId = getTestId(state.currentCandidateId, language);
    if (state.tests[testId]) return state.tests[testId];

    const question = pickRandomQuestion(language);
    state.tests[testId] = {
      id: testId,
      candidateId: state.currentCandidateId,
      language,
      questionId: question.id,
      questionSnapshot: { ...question },
      attempts: [],
      selectedAttemptId: null,
      createdAt: new Date().toISOString()
    };
    return state.tests[testId];
  }

  function getTestId(candidateId, language) {
    return `${candidateId}_${language}`;
  }

  function pickRandomQuestion(language) {
    const enabled = questions.filter((q) => q.language === language && q.enabled);
    const pool = enabled.length ? enabled : questions.filter((q) => q.language === language);
    return pool[Math.floor(Math.random() * pool.length)];
  }

  async function renderTests() {
    els.testCards.innerHTML = "";
    const tests = Object.values(state.tests).filter((test) => test.candidateId === state.currentCandidateId);
    if (!tests.length) {
      els.testCards.innerHTML = '<p class="hint">请选择语种并开始测评。</p>';
      return;
    }

    const template = document.getElementById("testCardTemplate");
    for (const test of tests) {
      const lang = LANGUAGES[test.language];
      const card = template.content.firstElementChild.cloneNode(true);
      const attemptsLeft = Math.max(0, MAX_ATTEMPTS - test.attempts.length);
      const finalAttempt = getFinalAttempt(test);

      card.dataset.language = test.language;
      card.querySelector(".locale").textContent = `${lang.locale} · ${test.questionSnapshot.difficulty}`;
      card.querySelector("h3").textContent = lang.label;
      card.querySelector(".scene").textContent = `场景：${test.questionSnapshot.scene}`;
      card.querySelector(".prompt").textContent = test.questionSnapshot.text;
      card.querySelector(".status-pill").textContent = finalAttempt ? decisionText(finalAttempt.decision) : "待录制";
      card.querySelector(".status-pill").className = `status-pill ${finalAttempt ? decisionClass(finalAttempt.decision) : ""}`;
      card.querySelector(".attempt-line").textContent = `已录制 ${test.attempts.length}/${MAX_ATTEMPTS} 次，剩余 ${attemptsLeft} 次。`;
      renderScorePanel(card.querySelector(".score-panel"), finalAttempt);
      await renderHistory(card.querySelector(".history-list"), test);

      const recordButton = card.querySelector(".record");
      const stopButton = card.querySelector(".stop");
      const submitButton = card.querySelector(".submit");
      const retakeButton = card.querySelector(".retake");
      const playback = card.querySelector(".playback");
      const latest = test.attempts[test.attempts.length - 1];

      if (latest) {
        const blob = await loadVideo(latest.blobKey);
        if (blob) {
          playback.src = URL.createObjectURL(blob);
          playback.style.display = "block";
        }
      }

      recordButton.disabled = attemptsLeft === 0 || Boolean(test.selectedAttemptId);
      submitButton.disabled = !latest || Boolean(test.selectedAttemptId);
      retakeButton.disabled = !latest || attemptsLeft === 0 || Boolean(test.selectedAttemptId);

      recordButton.addEventListener("click", () => startRecording(test.language, card));
      stopButton.addEventListener("click", stopRecording);
      submitButton.addEventListener("click", () => submitLatestAttempt(test.language));
      retakeButton.addEventListener("click", () => startRecording(test.language, card));

      els.testCards.appendChild(card);
    }
  }

  function renderScorePanel(container, attempt) {
    if (!attempt) {
      container.innerHTML = '<p class="hint">录制后会生成发音、流利度、完整度和综合建议。</p>';
      return;
    }
    container.innerHTML = [
      ["发音", attempt.scores.pronunciation],
      ["流利度", attempt.scores.fluency],
      ["完整度", attempt.scores.completeness],
      ["综合", attempt.scores.overall]
    ]
      .map(([label, value]) => `<div class="score-chip"><strong>${value}</strong>${label}</div>`)
      .join("");
  }

  async function renderHistory(container, test) {
    container.innerHTML = "";
    if (!test.attempts.length) {
      container.innerHTML = '<p class="hint">暂无历史录制。</p>';
      return;
    }

    for (const attempt of test.attempts) {
      const item = document.createElement("div");
      item.className = "history-item";
      const blob = await loadVideo(attempt.blobKey);
      const url = blob ? URL.createObjectURL(blob) : "";
      item.innerHTML = `
        <video controls src="${url}"></video>
        <div>
          <strong>第 ${attempt.attemptNumber} 次 · ${decisionText(attempt.decision)}</strong>
          <p class="report-meta">${formatTime(attempt.createdAt)} · 时长 ${attempt.duration}s · ${attempt.deviceInfo}</p>
          <p class="report-meta">转写/备注：${attempt.transcript}</p>
        </div>
      `;
      container.appendChild(item);
    }
  }

  async function startRecording(language, card) {
    if (recorder && recorder.state === "recording") {
      setHint("当前已有录制正在进行，请先停止。", true);
      return;
    }

    const test = state.tests[getTestId(state.currentCandidateId, language)];
    if (test.attempts.length >= MAX_ATTEMPTS) {
      setHint("该语种已达到 3 次录制上限。", true);
      return;
    }

    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
    } catch (error) {
      setHint("无法访问摄像头或麦克风。请检查浏览器权限后重试。", true);
      return;
    }

    chunks = [];
    activeLanguage = language;
    activeStartedAt = Date.now();
    const mimeType = MediaRecorder.isTypeSupported("video/webm;codecs=vp8,opus") ? "video/webm;codecs=vp8,opus" : "video/webm";
    recorder = new MediaRecorder(mediaStream, { mimeType });

    const live = card.querySelector(".live");
    live.srcObject = mediaStream;
    live.play();

    recorder.ondataavailable = (event) => {
      if (event.data.size) chunks.push(event.data);
    };
    recorder.onstop = () => finishRecording();
    recorder.start();

    card.querySelector(".record").disabled = true;
    card.querySelector(".stop").disabled = false;
    setHint("正在录制。录完后请停止并选择提交或重新录制。");
  }

  function stopRecording() {
    if (recorder && recorder.state === "recording") recorder.stop();
  }

  async function finishRecording() {
    const language = activeLanguage;
    const test = state.tests[getTestId(state.currentCandidateId, language)];
    const attemptNumber = test.attempts.length + 1;
    const duration = Math.max(1, Math.round((Date.now() - activeStartedAt) / 1000));
    const blob = new Blob(chunks, { type: recorder.mimeType || "video/webm" });
    const attemptId = createId("attempt");
    const blobKey = `${attemptId}.webm`;
    const assessment = simulateAssessment(test, duration);

    await saveVideo(blobKey, blob);
    test.attempts.push({
      id: attemptId,
      attemptNumber,
      blobKey,
      createdAt: new Date().toISOString(),
      duration,
      deviceInfo: getDeviceInfo(),
      transcript: assessment.transcript,
      scores: assessment.scores,
      decision: assessment.decision,
      reasons: assessment.reasons
    });

    cleanupRecorder();
    saveState();
    setHint(`${LANGUAGES[language].label} 第 ${attemptNumber} 次录制已存档。`);
    renderAll();
  }

  function cleanupRecorder() {
    if (mediaStream) {
      mediaStream.getTracks().forEach((track) => track.stop());
    }
    mediaStream = null;
    recorder = null;
    chunks = [];
    activeLanguage = null;
    activeStartedAt = null;
  }

  function submitLatestAttempt(language) {
    const test = state.tests[getTestId(state.currentCandidateId, language)];
    const latest = test.attempts[test.attempts.length - 1];
    if (!latest) return;
    test.selectedAttemptId = latest.id;
    saveState();
    setHint(`${LANGUAGES[language].label} 已提交。本语种不能再重录。`);
    renderAll();
  }

  function getFinalAttempt(test) {
    if (!test.attempts.length) return null;
    return test.attempts.find((attempt) => attempt.id === test.selectedAttemptId) || test.attempts[test.attempts.length - 1];
  }

  function simulateAssessment(test, duration) {
    const mode = LANGUAGES[test.language].mode;
    const textLength = test.questionSnapshot.text.length;
    const durationFit = Math.min(100, Math.round((duration / Math.max(18, textLength / 8)) * 82));
    const base = 58 + Math.floor(Math.random() * 32);
    const pronunciation = clamp(base + Math.floor(Math.random() * 10) - 4);
    const fluency = clamp(Math.round((base + durationFit) / 2) + Math.floor(Math.random() * 8) - 4);
    const completeness = clamp(mode === "scenario" ? base + 5 : Math.round((base + durationFit) / 2));
    const prosody = clamp(base + Math.floor(Math.random() * 12) - 6);
    const overall = Math.round(pronunciation * 0.35 + fluency * 0.25 + completeness * 0.25 + prosody * 0.15);
    const decision = overall >= 80 && completeness >= 78 ? "pass" : overall < 58 || completeness < 55 ? "reject" : "review";
    const transcript =
      mode === "scenario"
        ? "系统占位转写：候选人根据中文教学场景进行了英语表达。正式版接入英语转写与教学语境评分。"
        : `系统占位转写：候选人朗读了「${test.questionSnapshot.scene}」题目。正式版接入 ${LANGUAGES[test.language].locale} 发音评估。`;
    const reasons = {
      pass: "综合表现达到自动通过阈值。",
      reject: "综合分或完整度低于自动淘汰阈值。",
      review: "结果处于灰区，建议招聘老师人工复核原视频。"
    };

    return {
      transcript,
      scores: { pronunciation, fluency, completeness, prosody, overall },
      decision,
      reasons: reasons[decision]
    };
  }

  function clamp(value) {
    return Math.max(0, Math.min(100, value));
  }

  function getDeviceInfo() {
    const platform = navigator.platform || "unknown platform";
    const width = window.screen ? window.screen.width : "?";
    const height = window.screen ? window.screen.height : "?";
    return `${platform} · ${width}x${height}`;
  }

  function setHint(message, isError) {
    els.candidateHint.textContent = message;
    els.candidateHint.style.color = isError ? "var(--danger)" : "var(--muted)";
  }

  function resetCandidate() {
    cleanupRecorder();
    startFreshCandidate();
    hydrateCandidateInputs();
    els.languageChoices.querySelectorAll("input").forEach((input) => {
      input.checked = false;
    });
    setHint("已创建新的候选人记录。");
    renderAll();
  }

  function startFreshCandidate() {
    state.currentCandidateId = createId("candidate");
    ensureCandidate();
    saveState();
  }

  function renderReports() {
    const candidates = Object.values(state.candidates).sort((a, b) => b.createdAt.localeCompare(a.createdAt));
    const tests = Object.values(state.tests);
    const finalAttempts = tests.map(getFinalAttempt).filter(Boolean);
    els.reportSummary.innerHTML = [
      ["候选人", candidates.length],
      ["语种测试", tests.length],
      ["已存档录制", tests.reduce((sum, test) => sum + test.attempts.length, 0)],
      ["需复核", finalAttempts.filter((attempt) => attempt.decision === "review").length]
    ]
      .map(([label, value]) => `<div class="summary-box"><strong>${value}</strong>${label}</div>`)
      .join("");

    els.reports.innerHTML = "";
    if (!candidates.length) {
      els.reports.innerHTML = '<p class="hint">暂无候选人报告。</p>';
      return;
    }

    candidates.forEach((candidate) => {
      const candidateTests = tests.filter((test) => test.candidateId === candidate.id);
      const card = document.createElement("article");
      card.className = "report-card";
      card.innerHTML = `
        <div class="report-head">
          <div>
            <h3>${escapeHtml(candidate.name || "未填写姓名")}</h3>
            <p class="report-meta">${escapeHtml(candidate.role || "未填写岗位")} · ${formatTime(candidate.createdAt)}</p>
          </div>
        </div>
        <div class="report-languages"></div>
      `;
      const list = card.querySelector(".report-languages");
      if (!candidateTests.length) {
        list.innerHTML = '<p class="hint">尚未开始任何语种测试。</p>';
      } else {
        candidateTests.forEach((test) => renderReportLanguage(list, test));
      }
      els.reports.appendChild(card);
    });
  }

  async function renderReportLanguage(container, test) {
    const lang = LANGUAGES[test.language];
    const finalAttempt = getFinalAttempt(test);
    const node = document.createElement("div");
    node.className = "report-language";
    node.innerHTML = `
      <div class="report-head">
        <div>
          <strong>${lang.label}</strong>
          <p class="report-meta">${lang.locale} · 题目：${escapeHtml(test.questionSnapshot.scene)} · 录制 ${test.attempts.length}/${MAX_ATTEMPTS} 次</p>
        </div>
        <span class="decision-pill ${finalAttempt ? decisionClass(finalAttempt.decision) : ""}">${finalAttempt ? decisionText(finalAttempt.decision) : "待录制"}</span>
      </div>
      <p>${escapeHtml(test.questionSnapshot.text)}</p>
      <div class="score-panel"></div>
      <p class="report-meta">${finalAttempt ? escapeHtml(finalAttempt.reasons) : "暂无评分。"}</p>
    `;
    renderScorePanel(node.querySelector(".score-panel"), finalAttempt);
    if (finalAttempt) {
      const blob = await loadVideo(finalAttempt.blobKey);
      if (blob) {
        const video = document.createElement("video");
        video.controls = true;
        video.src = URL.createObjectURL(blob);
        node.appendChild(video);
      }
    }
    container.appendChild(node);
  }

  function clearReports() {
    if (!confirm("确定清空所有候选人和录制记录吗？题库不会被删除。")) return;
    localStorage.removeItem(STORAGE_KEY);
    Object.keys(state).forEach((key) => delete state[key]);
    Object.assign(state, loadState());
    hydrateCandidateInputs();
    renderAll();
  }

  function renderQuestions() {
    els.questionBank.innerHTML = "";
    Object.keys(LANGUAGES).forEach((language) => {
      const group = document.createElement("section");
      const lang = LANGUAGES[language];
      const items = questions.filter((q) => q.language === language);
      const enabledCount = items.filter((q) => q.enabled).length;
      group.innerHTML = `<h3>${lang.label} <span class="report-meta">${enabledCount} 条启用 / ${items.length} 条总计</span></h3>`;
      items.forEach((question) => {
        const card = document.createElement("article");
        card.className = `question-card ${question.enabled ? "" : "disabled"}`;
        card.innerHTML = `
          <div class="question-head">
            <div>
              <strong>${escapeHtml(question.scene)}</strong>
              <p class="question-meta">${question.difficulty} · v${question.version} · ${question.enabled ? "启用" : "停用"}</p>
            </div>
            <div class="question-actions">
              <button type="button" data-action="edit">编辑</button>
              <button type="button" data-action="toggle">${question.enabled ? "停用" : "启用"}</button>
            </div>
          </div>
          <p>${escapeHtml(question.text)}</p>
        `;
        card.querySelector('[data-action="edit"]').addEventListener("click", () => editQuestion(question.id));
        card.querySelector('[data-action="toggle"]').addEventListener("click", () => toggleQuestion(question.id));
        group.appendChild(card);
      });
      els.questionBank.appendChild(group);
    });
  }

  function saveQuestionFromForm(event) {
    event.preventDefault();
    const language = els.questionLanguage.value;
    const scene = els.questionScene.value.trim();
    const difficulty = els.questionDifficulty.value;
    const text = els.questionText.value.trim();
    const editingId = els.editingQuestionId.value;

    if (!scene || !text) return;

    if (editingId) {
      const question = questions.find((q) => q.id === editingId);
      question.language = language;
      question.scene = scene;
      question.difficulty = difficulty;
      question.text = text;
      question.version += 1;
      question.updatedAt = new Date().toISOString();
    } else {
      questions.push({
        id: createId("q"),
        language,
        scene,
        difficulty,
        text,
        enabled: true,
        version: 1,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString()
      });
    }

    saveQuestions();
    clearQuestionForm();
    renderQuestions();
  }

  function editQuestion(id) {
    const question = questions.find((q) => q.id === id);
    els.questionLanguage.value = question.language;
    els.questionScene.value = question.scene;
    els.questionDifficulty.value = question.difficulty;
    els.questionText.value = question.text;
    els.editingQuestionId.value = question.id;
    switchView("questions");
  }

  function toggleQuestion(id) {
    const question = questions.find((q) => q.id === id);
    question.enabled = !question.enabled;
    question.updatedAt = new Date().toISOString();
    saveQuestions();
    renderQuestions();
  }

  function clearQuestionForm() {
    els.questionForm.reset();
    els.editingQuestionId.value = "";
  }

  function decisionText(decision) {
    return { pass: "通过", reject: "淘汰", review: "人工复核" }[decision] || "待录制";
  }

  function decisionClass(decision) {
    return { pass: "decision-pass", reject: "decision-reject", review: "decision-review" }[decision] || "";
  }

  function formatTime(value) {
    return new Intl.DateTimeFormat("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit"
    }).format(new Date(value));
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function openDb() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, 1);
      request.onupgradeneeded = () => request.result.createObjectStore(DB_STORE);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  async function saveVideo(key, blob) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(DB_STORE, "readwrite");
      tx.objectStore(DB_STORE).put(blob, key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  }

  async function loadVideo(key) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(DB_STORE, "readonly");
      const request = tx.objectStore(DB_STORE).get(key);
      request.onsuccess = () => resolve(request.result || null);
      request.onerror = () => reject(request.error);
    });
  }

  function renderAll() {
    renderTests();
    renderReports();
    renderQuestions();
  }

  init();
})();
