import React, { useState, useEffect, useRef } from 'react';
import {
  Send, PawPrint, CheckCircle2, XCircle,
  CreditCard, MapPin, Clock, RefreshCw, Train,
  Plane, CloudSun, MessageSquare, LayoutList, ShieldCheck,
  ChevronLeft, Lock, Check, Smartphone, Building2, Printer, MessageCircle
} from 'lucide-react';
import { INITIAL_MESSAGES } from './mockData';
import { getQuickActions } from './quickActions';
import { shiftedCheckout } from './tripDates';
import { partyDetails, partyLabel, validPartyDraft, ageLabel, loyaltyPoints } from './tripDetails';
import { fetchInitialTrips, sendChatMessage, createBooking, startNewChat } from './tripApi';
import ChatMessage from './ChatMessage';

function chatMessage(sender, text) {
  const timestamp = new Date();
  return {
    id: globalThis.crypto?.randomUUID?.() || `${timestamp.getTime()}-${Math.random()}`,
    sender, text,
    time: timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
  };
}

export default function App() {
  const [tripOptions, setTripOptions] = useState({});
  const [messages, setMessages] = useState(INITIAL_MESSAGES);
  const [inputValue, setInputValue] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [isInitializing, setIsInitializing] = useState(true);
  const [chatError, setChatError] = useState('');
  const [agentMode, setAgentMode] = useState('');
  const [planMessage, setPlanMessage] = useState('');
  const [planStatus, setPlanStatus] = useState('empty');
  const [chatState, setChatState] = useState({});
  const [isDateEditorOpen, setIsDateEditorOpen] = useState(false);
  const [dateDraft, setDateDraft] = useState('');
  const [checkoutDraft, setCheckoutDraft] = useState('');
  const [depTimeDraft, setDepTimeDraft] = useState('08:30');
  const [arrTimeDraft, setArrTimeDraft] = useState('12:45');
  const [isGuestEditorOpen, setIsGuestEditorOpen] = useState(false);
  const [guestDraft, setGuestDraft] = useState(2);
  const [childrenDraft, setChildrenDraft] = useState([]);
  const [isOriginEditorOpen, setIsOriginEditorOpen] = useState(false);
  const [originDraft, setOriginDraft] = useState('Москва');
  const [departureCities, setDepartureCities] = useState(['Москва', 'Санкт-Петербург', 'Казань', 'Екатеринбург']);
  const [petDraft, setPetDraft] = useState(false);
  const [isPointsOpen, setIsPointsOpen] = useState(false);
  const [todayISO] = useState(() => new Date().toISOString().slice(0, 10));
  const inputRef = useRef(null);
  const sendingRef = useRef(false);

  const [selectedOptionKey, setSelectedOptionKey] = useState('A');
  const [viewMode, setViewMode] = useState(() => {
    return window.location.hash.replace('#', '') || 'canvas';
  }); // 'canvas' | 'compare' | 'itinerary' | 'checkout'
  const [isChatOpen, setIsChatOpen] = useState(true);
  const messagesEndRef = useRef(null);
  const chatContainerRef = useRef(null);

  const [isBookingLoading, setIsBookingLoading] = useState(false);
  const [paymentMethod, setPaymentMethod] = useState('sbp');
  const [bookingInfo, setBookingInfo] = useState({
    voucherId: 'OST-7741902',
    pnr: 'РЖД-8841209'
  });

  const scrollToBottom = () => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTo({
        top: chatContainerRef.current.scrollHeight,
        behavior: 'smooth'
      });
    }
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  const changeViewMode = (newMode, pushHistory = true) => {
    setViewMode(newMode);
    if (newMode !== 'canvas') {
      setIsOriginEditorOpen(false);
      setIsGuestEditorOpen(false);
      setIsDateEditorOpen(false);
    }
    if (window.innerWidth < 768 && newMode !== 'canvas') {
      setIsChatOpen(false);
    }
    if (pushHistory) {
      window.history.pushState({ viewMode: newMode }, '', `#${newMode}`);
    }
  };

  useEffect(() => {
    const handlePopState = (e) => {
      const mode = e.state?.viewMode || window.location.hash.replace('#', '') || 'canvas';
      setViewMode(mode);
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, isTyping]);

  useEffect(() => {
    let cancelled = false;
    fetchInitialTrips().then((data) => {
      if (cancelled) return;
      if (data.options) setTripOptions(data.options);
      else if (data && data.A && data.B) setTripOptions({ A: data.A, B: data.B });
      setPlanMessage(data.planMessage || 'Опишите поездку в чате — подходящие варианты появятся здесь.');
      setPlanStatus(data.planStatus || 'empty');
      setChatState(data.chatState || {});
      if (data.departureCities?.length) setDepartureCities(data.departureCities);
      if (data.selectedOption) setSelectedOptionKey(data.selectedOption);
      if (data.messages?.length) setMessages(data.messages.map((m, index) => ({
        id: `history-${index}`, sender: m.role === 'user' ? 'user' : 'ai', text: m.content,
      })));
      setAgentMode(data.agent || 'demo');
    }).catch((error) => {
      if (!cancelled) setChatError(error.message || 'Не удалось загрузить поездки. Проверьте соединение.');
    }).finally(() => {
      if (!cancelled) setIsInitializing(false);
    });
    return () => { cancelled = true; };
  }, []);

  const availableOptionKeys = ['A', 'B'].filter((key) => {
    const opt = tripOptions[key];
    if (!opt || opt.available === false) return false;
    if (key === 'B' && tripOptions.A?.hotel?.id && opt.hotel?.id && opt.hotel.id === tripOptions.A.hotel.id) return false;
    return true;
  });
  const hasPlan = availableOptionKeys.length > 0;
  const currentTrip = availableOptionKeys.includes(selectedOptionKey) ? tripOptions[selectedOptionKey] : tripOptions[availableOptionKeys[0]];
  const party = partyDetails(chatState, currentTrip);
  const tripWithPet = (chatState.pet_friendly !== undefined ? Boolean(chatState.pet_friendly) : undefined) ?? currentTrip?.travellers?.withPet ?? false;
  const transportData = currentTrip?.transport || currentTrip?.flight || { price: 0 };

  const hotelTotal = currentTrip ? currentTrip.hotel.pricePerNight * currentTrip.hotel.nights : 0;
  const extrasTotal =
    (currentTrip?.extras || []).reduce((acc, item) => acc + item.price, 0);
  const grandTotal = transportData.price + hotelTotal + extrasTotal;

  const quickActions = getQuickActions({ options: tripOptions, selected: selectedOptionKey, viewMode, state: chatState, planStatus });

  const openDateEditor = () => {
    const start = chatState.checkin_date || todayISO;
    const nights = chatState.nights || currentTrip?.hotel?.nights || 4;
    const end = chatState.checkout_date || shiftedCheckout(start, nights);
    setDateDraft(start);
    setCheckoutDraft(end);
    setDepTimeDraft(transportData?.depTime || '08:30');
    setArrTimeDraft(transportData?.arrTime || '12:45');
    setIsDateEditorOpen(true);
    setIsOriginEditorOpen(false);
    setIsGuestEditorOpen(false);
    changeViewMode('canvas');
    if (window.innerWidth < 768) setIsChatOpen(false);
  };
  const dateNights = chatState.nights || currentTrip?.hotel?.nights || 4;
  const headerDatesLabel = (() => {
    if (chatState.checkin_date && chatState.checkout_date) {
      const formatDate = (iso) => {
        const parts = String(iso).split('-');
        return parts.length === 3 ? `${parts[2]}.${parts[1]}.${parts[0]}` : iso;
      };
      const n = chatState.nights || Math.max(1, Math.round((new Date(chatState.checkout_date) - new Date(chatState.checkin_date)) / 86400000));
      return `${formatDate(chatState.checkin_date)} — ${formatDate(chatState.checkout_date)} • ${n} ноч.`;
    }
    if (chatState.nights && (!hasPlan || chatState.nights !== currentTrip?.hotel?.nights)) {
      if (currentTrip?.dates) {
        return currentTrip.dates.replace(/\d+\s*ноч\w*/, `${chatState.nights} ноч.`);
      }
      return `${chatState.nights} ноч.`;
    }
    return currentTrip?.dates || chatState.checkin_date || 'Указать даты';
  })();
  const openGuestEditor = () => {
    setGuestDraft(party.adults);
    setChildrenDraft(party.children_ages.map(String));
    setIsOriginEditorOpen(false);
    setPetDraft(tripWithPet);
    setIsGuestEditorOpen(true);
    setIsDateEditorOpen(false);
    setChatError('');
    changeViewMode('canvas');
    if (window.innerWidth < 768) setIsChatOpen(false);
  };
  const travelStyleLabel = (chatState.travel_styles || []).map(style => ({ mountains: 'горы', sea: 'море' })[style]).filter(Boolean).join(' и ');
  const openOriginEditor = () => {
    setOriginDraft(chatState.origin || transportData.depCity || 'Москва');
    setIsOriginEditorOpen(true);
    setIsGuestEditorOpen(false);
    setIsDateEditorOpen(false);
    setChatError('');
    changeViewMode('canvas');
    if (window.innerWidth < 768) setIsChatOpen(false);
  };
  const handleQuickAction = (chip) => {
    if (chip.local === 'dates') return openDateEditor();
    if (chip.local === 'guests') return openGuestEditor();
    if (chip.local === 'origin') return openOriginEditor();
    if (chip.local === "print") return window.print();
    if (chip.local === "new") return startNewChat();
    if (chip.fill) {
      setInputValue(chip.fill);
      inputRef.current?.focus();
      return;
    }
    handleSendMessage(chip.actionText, chip.actionId, chip.actionData);
  };

  const handleSendMessage = async (text, actionId = null, actionData = {}) => {
    if (!text.trim() || sendingRef.current || isInitializing) return;
    sendingRef.current = true;
    setChatError('');

    const userMsg = chatMessage('user', text);

    setMessages((prev) => [...prev, userMsg]);
    setInputValue('');
    if (inputRef.current) {
      inputRef.current.style.height = 'auto';
    }
    setIsTyping(true);
    setTimeout(scrollToBottom, 30);

    try {
      const backendData = await sendChatMessage(text, selectedOptionKey, actionId, actionData);
      if (!backendData) throw new Error('Не удалось получить ответ агента.');
      if (backendData.updatedOptions) setTripOptions(backendData.updatedOptions);
      setPlanMessage(backendData.planMessage || 'Нет готовых вариантов под текущие условия. Уточните запрос в чате.');
      setPlanStatus(backendData.planStatus || 'empty');
      setChatState(backendData.chatState || {});
      if (backendData.selectedOption) setSelectedOptionKey(backendData.selectedOption);
      if (backendData.viewMode) changeViewMode(backendData.viewMode);
      if (backendData.agent) setAgentMode(backendData.agent);
      setMessages((prev) => [
        ...prev,
        chatMessage('ai', backendData.reply || 'План поездки обновлен.')
      ]);
      setTimeout(scrollToBottom, 50);
      if (backendData.changeRejected) setChatError(backendData.reply);
      return !backendData.changeRejected;
    } catch (error) {
      setMessages((prev) => prev.filter((msg) => msg.id !== userMsg.id));
      setChatError(error.message || 'Не удалось отправить сообщение. Попробуйте ещё раз.');
      setInputValue(text);
      return false;
    } finally {
      sendingRef.current = false;
      setIsTyping(false);
    }
  };

  const handleStartCheckout = () => {
    if (!hasPlan) return;
    changeViewMode('checkout');
  };

  const handleConfirmPayment = async () => {
    if (!hasPlan) return;
    setIsBookingLoading(true);
    const result = await createBooking(currentTrip, grandTotal);

    setTimeout(() => {
      if (result) {
        setBookingInfo({
          voucherId: result.voucherId || result.voucher_id || 'OST-7741902',
          pnr: result.pnr || result.pnr_code || 'AERO-8841209',
          issuedAt: result.issued_at || new Date().toLocaleDateString('ru-RU'),
          travellers: result.voucher?.travellers || { ...party, withPet: tripWithPet },
        });
      }
      setIsBookingLoading(false);
      changeViewMode('itinerary');
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now(),
          sender: 'ai',
          text: `Оплата прошла успешно! Сформировал ваш маршрутный лист и ваучер для поездки «${currentTrip.title}».`,
          time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        }
      ]);
    }, 1000);
  };

  const handleReturnToCanvas = () => {
    changeViewMode('canvas');
  };

  return (
    <div className="min-h-screen md:h-screen w-full bg-[#D8F8A2] text-gray-900 flex flex-col font-sans overflow-x-hidden relative">

      <style>{`
        .no-scrollbar::-webkit-scrollbar {
          display: none;
        }
        .no-scrollbar {
          -ms-overflow-style: none;
          scrollbar-width: none;
        }
      `}</style>

      {/* ПЛАВАЮЩАЯ СИНЯЯ КРУГЛАЯ КНОПКА СЛЕВА ВНИЗУ */}
      {!isChatOpen && !isGuestEditorOpen && !isDateEditorOpen && !isOriginEditorOpen && (
        <button
          onClick={() => setIsChatOpen(true)}
          title="Открыть чат с ИИ"
          className="fixed bottom-6 left-6 z-50 w-14 h-14 rounded-full bg-[#1943EB] hover:bg-blue-700 text-white flex items-center justify-center shadow-2xl border-2 border-white cursor-pointer transition transform hover:scale-105 print:hidden"
        >
          <MessageCircle className="w-7 h-7" />
        </button>
      )}

      {/* ШАПКА */}
      <header className="bg-[#D8F8A2] px-4 py-3 flex flex-wrap items-center justify-between gap-2 shrink-0 border-b border-[#C2E886] print:hidden">
        <div className="flex flex-wrap items-center gap-3">
          <div className="text-2xl font-black text-[#1943EB] tracking-tight">
            TravelAIChatbot
          </div>

          {(hasPlan || chatState.origin || chatState.destination || chatState.passengers || chatState.checkin_date || chatState.nights) && <div className="flex flex-wrap items-center bg-white rounded-2xl px-3 py-1.5 shadow-xs border border-gray-200 text-xs gap-2">
            <span className="font-bold text-gray-800 flex items-center gap-1">
              <Building2 className="w-3.5 h-3.5 text-[#1943EB]" /> {chatState.destination || (hasPlan ? (currentTrip?.destination?.split('→')[1]?.trim() || currentTrip?.title) : 'Куда угодно') || 'Поездка'}
            </span>
            <button aria-label="Изменить город вылета" onClick={openOriginEditor} disabled={isTyping || isInitializing} className="rounded-lg px-2 py-1.5 text-[#1943EB] hover:bg-blue-50 font-semibold">Вылет: {chatState.origin || transportData.depCity || 'Москва'} ✎</button>
            <span className="text-gray-300">|</span>
            <button aria-label="Изменить даты поездки" onClick={openDateEditor} disabled={isTyping || isInitializing} className="rounded-lg px-2 py-1.5 text-[#1943EB] hover:bg-blue-50 font-semibold disabled:opacity-50">{headerDatesLabel} ✎</button>
            <span className="text-gray-300">|</span>
            <button aria-label="Изменить количество гостей" onClick={openGuestEditor} disabled={isTyping || isInitializing} className="rounded-lg px-2 py-1.5 text-[#1943EB] hover:bg-blue-50 font-semibold disabled:opacity-50">{partyLabel(party)} ✎</button>
          </div>}
        </div>

        <div className="flex items-center gap-2">
          {!isChatOpen && (
            <button
              onClick={() => setIsChatOpen(true)}
              className="bg-white hover:bg-gray-50 text-[#1943EB] px-3.5 py-1.5 rounded-full text-xs font-bold cursor-pointer transition shadow-2xs border border-gray-200 flex items-center gap-1.5"
            >
              <MessageSquare className="w-3.5 h-3.5" />
              Открыть чат
            </button>
          )}
          {viewMode !== 'canvas' && (
            <button
              onClick={handleReturnToCanvas}
              className="bg-white hover:bg-gray-50 text-gray-800 px-3.5 py-1.5 rounded-full text-xs font-bold cursor-pointer transition shadow-2xs border border-gray-200"
            >
              ← Вернуться к плану
            </button>
          )}
          {hasPlan && <div className="relative" onMouseEnter={() => setIsPointsOpen(true)} onMouseLeave={() => setIsPointsOpen(false)}>
            <button aria-label="Как начисляются бонусные баллы" aria-describedby={isPointsOpen ? 'points-tooltip' : undefined} onFocus={() => setIsPointsOpen(true)} onBlur={() => setIsPointsOpen(false)} onClick={() => setIsPointsOpen(true)} className="text-xs bg-[#1943EB] text-white px-3.5 py-1.5 rounded-full font-bold shadow-xs cursor-help">
              +{loyaltyPoints(grandTotal).toLocaleString('ru-RU')} баллов
            </button>
            {isPointsOpen && <div role="tooltip" id="points-tooltip" className="absolute right-0 top-full mt-2 z-50 w-72 max-w-[calc(100vw-32px)] rounded-2xl border border-blue-100 bg-white p-4 text-gray-900 shadow-xl text-sm leading-relaxed">
              <p className="font-bold text-[#1943EB]">Бонусные баллы за поездку</p>
              <p className="mt-1">Начислим {loyaltyPoints(grandTotal).toLocaleString('ru-RU')} баллов: 1,5% от {grandTotal.toLocaleString('ru-RU')} ₽, минимум 150.</p>
              <p className="mt-2 text-xs text-gray-500">Начисление баллов демонстрационное.</p>
            </div>}
          </div>}
        </div>
      </header>

      {/* ПЕРЕКЛЮЧАТЕЛЬ ДЛЯ ТЕЛЕФОНОВ (< 768px) */}
      <div className="md:hidden grid grid-cols-2 bg-white border-b border-gray-200 shrink-0 print:hidden">
        <button
          onClick={() => setIsChatOpen(true)}
          className={`py-2.5 text-sm font-semibold flex items-center justify-center gap-1.5 border-b-2 ${
            isChatOpen
              ? 'border-[#1943EB] text-[#1943EB] bg-blue-50/50'
              : 'border-transparent text-gray-600'
          }`}
        >
          <MessageSquare className="w-4 h-4" />
          Чат с ИИ
        </button>
        <button
          onClick={() => setIsChatOpen(false)}
          className={`py-2.5 text-sm font-semibold flex items-center justify-center gap-1.5 border-b-2 ${
            !isChatOpen
              ? 'border-[#1943EB] text-[#1943EB] bg-blue-50/50'
              : 'border-transparent text-gray-600'
          }`}
        >
          <LayoutList className="w-4 h-4" />
          {hasPlan ? `План (${grandTotal.toLocaleString('ru-RU')} ₽)` : 'План поездки'}
        </button>
      </div>

      {/* ОСНОВНОЙ КОНТЕЙНЕР SPLIT SCREEN */}
      <div className="flex-1 flex flex-col md:flex-row md:overflow-hidden relative">

        {/* ЛЕВАЯ КОЛОНКА: ЧАТ */}
        {isChatOpen && (
          <section className="w-full md:w-[380px] lg:w-[420px] border-r border-[#C2E886] bg-white flex flex-col h-[calc(100vh-110px)] md:h-full overflow-hidden shrink-0 print:hidden">
            <div className="px-4 py-3 border-b border-gray-200 bg-gray-50 flex items-center justify-between text-xs text-gray-600 shrink-0">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-[#1943EB] animate-pulse" />
                <span className="font-bold text-gray-800">ИИ-помощник по поездкам</span>
              </div>
              <button
                onClick={startNewChat}
                disabled={isTyping || isInitializing}
                className="text-[#1943EB] font-bold px-2 py-1 rounded hover:bg-blue-50 disabled:opacity-50"
              >
                Новый чат
              </button>
              <button
                onClick={() => setIsChatOpen(false)}
                className="flex items-center gap-1 bg-gray-200 hover:bg-gray-300 text-gray-700 px-2.5 py-1 rounded-lg text-xs font-bold cursor-pointer transition"
              >
                <span>Спрятать чат</span>
                <ChevronLeft className="w-3.5 h-3.5" />
              </button>
            </div>

            <div ref={chatContainerRef} className="flex-1 min-w-0 overflow-y-auto no-scrollbar p-4 space-y-3 bg-[#FAFAFA]">
              {messages.map((msg) => (
                <div
                  key={msg.id}
                  className={`flex min-w-0 max-w-full flex-col ${msg.sender === 'user' ? 'items-end' : 'items-start'}`}
                >
                  <div
                    className={`min-w-0 rounded-2xl px-4 py-2.5 text-sm border shadow-2xs ${
                      msg.sender === 'user'
                        ? 'max-w-[85%] bg-[#1943EB] text-white border-[#1943EB] font-medium whitespace-pre-wrap break-words'
                        : 'max-w-[95%] bg-white text-gray-900 border-gray-200 font-normal'
                    }`}
                  >
                    {msg.sender === 'user' ? msg.text : <ChatMessage text={msg.text} />}
                  </div>
                  <span className="text-[11px] text-gray-400 mt-1 px-1">{msg.time}</span>
                </div>
              ))}

              {isTyping && (
                <div className="text-xs text-gray-600 bg-white border border-gray-200 px-3.5 py-2 rounded-xl w-fit flex items-center gap-2 shadow-2xs font-medium">
                  <RefreshCw className="w-3.5 h-3.5 animate-spin text-[#1943EB]" />
                  ИИ подбирает лучшие билеты и отели...
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            <div className="p-3 border-t border-gray-200 bg-white shrink-0">
              {agentMode === 'demo' && (
                <p className="text-xs text-amber-800 mb-2">Деморежим: для ответов ИИ добавьте OPENROUTER_API_KEY или GROQ_API_KEY на сервере.</p>
              )}
              {chatError && <p role="alert" className="text-sm text-red-700 mb-2">{chatError}</p>}
              <div className="text-xs text-gray-500 mb-2 font-bold uppercase tracking-wider">Быстрые действия:</div>
              <div className="flex flex-wrap gap-1.5">
                {quickActions.map((chip) => (
                  <button
                    key={chip.id}
                    onClick={() => handleQuickAction(chip)}
                    disabled={isTyping || isInitializing}
                    className="text-xs bg-blue-50/60 hover:bg-blue-100 text-blue-900 border border-blue-200 px-3 py-1.5 rounded-xl cursor-pointer text-left transition font-semibold"
                  >
                    {chip.label}
                  </button>
                ))}
              </div>
            </div>

            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (inputValue.trim()) {
                  handleSendMessage(inputValue);
                  if (inputRef.current) {
                    inputRef.current.style.height = 'auto';
                    inputRef.current.style.overflowY = 'hidden';
                  }
                }
              }}
              className="p-3 border-t border-gray-200 bg-white flex items-end gap-2 shrink-0"
            >
              <textarea
                ref={inputRef}
                rows={2}
                value={inputValue}
                maxLength={6000}
                disabled={isInitializing}
                onChange={(e) => {
                  setInputValue(e.target.value);
                  e.target.style.height = 'auto';
                  const newHeight = Math.max(58, Math.min(e.target.scrollHeight, 180));
                  e.target.style.height = newHeight + 'px';
                  e.target.style.overflowY = e.target.scrollHeight > 180 ? 'auto' : 'hidden';
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    if (inputValue.trim() && !isTyping && !isInitializing) {
                      handleSendMessage(inputValue);
                      if (inputRef.current) {
                        inputRef.current.style.height = 'auto';
                        inputRef.current.style.overflowY = 'hidden';
                      }
                    }
                  }
                }}
                placeholder="Спросите о поездке, билетах или отеле..."
                style={{ minHeight: '58px', overflowY: 'hidden' }}
                className="flex-1 bg-gray-50 border border-gray-300 rounded-xl px-3.5 py-2.5 text-sm text-gray-900 focus:outline-none focus:border-[#1943EB] resize-none max-h-44 leading-relaxed"
              />
              <button
                type="submit"
                disabled={isTyping || isInitializing || !inputValue.trim()}
                className="bg-[#1943EB] hover:bg-blue-700 text-white px-4 py-2.5 h-[42px] rounded-xl text-sm font-bold flex items-center justify-center gap-1 cursor-pointer transition shadow-xs shrink-0 self-end"
              >
                <Send className="w-4 h-4" />
                <span className="hidden sm:inline">Отправить</span>
              </button>
            </form>
          </section>
        )}

        {/* ПРАВАЯ ЧАСТЬ: TRIP CANVAS (Небольшие аккуратные поля p-3 sm:p-4 без огромных пустот по бокам) */}
        <main
          className={`${
            isChatOpen ? 'hidden md:block' : 'block'
          } flex-1 bg-[#D8F8A2] overflow-y-auto no-scrollbar p-3 sm:p-4 lg:p-5 relative print:block print:bg-white print:p-0 print:overflow-visible`}
        >
          {isOriginEditorOpen && !['checkout', 'itinerary'].includes(viewMode) && (
            <form aria-label="Город вылета" onSubmit={async event => {
              event.preventDefault();
              const ok = await handleSendMessage(`Измени город вылета на ${originDraft}, остальные условия сохрани.`, 'change_origin', { origin: originDraft });
              if (ok) setIsOriginEditorOpen(false);
            }} className="max-w-xl mx-auto bg-white rounded-2xl p-5 mb-4 space-y-4 border border-blue-200">
              <h2 className="text-lg font-bold">Откуда отправляемся</h2>
              <label className="block text-sm font-semibold">Город вылета
                <select value={originDraft} onChange={e => setOriginDraft(e.target.value)} className="mt-1 block w-full border border-gray-300 rounded-xl px-3 py-2">
                  {departureCities.map(city => <option key={city} value={city}>{city}</option>)}
                </select>
              </label>
              <p className="text-xs text-gray-500">Проверим расписание, пересчитаем стоимость и сохраним ваш бюджет. Предпочтение — прямому авиарейсу.</p>
              {chatError && <p role="alert" className="text-red-700 text-sm">{chatError}</p>}
              <div className="flex gap-2">
                <button disabled={isTyping} className="rounded-xl bg-[#1943EB] text-white px-4 py-2 text-sm font-bold">Применить город</button>
                <button type="button" onClick={() => setIsOriginEditorOpen(false)} className="rounded-xl bg-gray-100 px-4 py-2 text-sm">Отмена</button>
              </div>
            </form>
          )}
          {isGuestEditorOpen && !['checkout', 'itinerary'].includes(viewMode) && (
            <form aria-label="Количество гостей" onSubmit={async event => {
              event.preventDefault();
              if (!validPartyDraft(guestDraft, childrenDraft)) return;
              const ok = await handleSendMessage(`Измени состав поездки: ${guestDraft} взрослых, дети: ${childrenDraft.length ? childrenDraft.join(', ') + ' лет' : 'без детей'}, ${petDraft ? 'с питомцем' : 'без питомцев'}.`, 'change_guests',
                { adults: Number(guestDraft), children_ages: childrenDraft.map(Number), pet_friendly: petDraft });
              if (ok) setIsGuestEditorOpen(false);
            }} className="max-w-xl mx-auto bg-white rounded-2xl p-5 mb-4 space-y-4 border border-blue-200">
              <h2 className="text-lg font-bold">Кто едет в поездку</h2>
              <label className="block text-sm font-semibold">Взрослые, от 18 лет
                <div className="flex gap-2 mt-1">
                  <button type="button" aria-label="Убрать взрослого" disabled={Number(guestDraft) <= 1} onClick={() => setGuestDraft(Number(guestDraft)-1)} className="rounded-xl border px-4">−</button>
                  <input aria-label="Количество взрослых" type="number" min="1" max={10-childrenDraft.length} step="1" required value={guestDraft} onChange={e => setGuestDraft(e.target.value)} className="block w-full border border-gray-300 rounded-xl px-3 py-2" />
                  <button type="button" aria-label="Добавить взрослого" disabled={Number(guestDraft)+childrenDraft.length >= 10} onClick={() => setGuestDraft(Number(guestDraft)+1)} className="rounded-xl border px-4">+</button>
                </div>
              </label>
              {childrenDraft.map((age, index) => <div key={index} className="flex gap-2 items-end">
                <label className="text-sm font-semibold flex-1">Ребёнок {index+1}: возраст на день вылета
                  <select required value={age} onChange={e => setChildrenDraft(previous => previous.map((v,i) => i===index ? e.target.value : v))} className="mt-1 block w-full border border-gray-300 rounded-xl px-3 py-2">
                    <option value="" disabled>Укажите возраст</option>
                    {Array.from({length:18},(_,value) => <option key={value} value={value}>{ageLabel(value)}</option>)}
                  </select>
                </label>
                <button type="button" aria-label={`Убрать ребёнка ${index+1}`} onClick={() => setChildrenDraft(previous => previous.filter((_,i) => i!==index))} className="rounded-xl border px-3 py-2">×</button>
              </div>)}
              <button type="button" disabled={Number(guestDraft)+childrenDraft.length >= 10} onClick={() => setChildrenDraft(previous => [...previous, ''])} className="rounded-xl border border-blue-200 text-blue-700 px-4 py-2 text-sm font-bold">+ Добавить ребёнка</button>
              <p className="text-xs text-gray-500">Демотариф: до 2 лет — 10% авиатарифа без места, 2–11 лет — 75%, с 12 лет — полный тариф. Номер на 2 места; младенец без отдельного места. Сбор — только для взрослых. На одного младенца нужен один взрослый.</p>
              <label className="flex items-center gap-2 text-sm font-semibold"><input type="checkbox" checked={petDraft} onChange={e => setPetDraft(e.target.checked)} />Еду с питомцем</label>
              {chatError && <p role="alert" className="text-red-700 text-sm">{chatError}</p>}
              <div className="flex gap-2">
                <button type="submit" disabled={isTyping || !validPartyDraft(guestDraft, childrenDraft)} className="rounded-xl bg-[#1943EB] text-white px-4 py-2 text-sm font-bold disabled:opacity-50">Применить гостей</button>
                <button type="button" onClick={() => setIsGuestEditorOpen(false)} className="rounded-xl bg-gray-100 px-4 py-2 text-sm">Отмена</button>
              </div>
            </form>
          )}
          {isDateEditorOpen && !['checkout', 'itinerary'].includes(viewMode) && (
            <form aria-label="Перенос дат поездки" onSubmit={async (event) => {
              event.preventDefault();
              const values = new FormData(event.currentTarget);
              const start = String(values.get('checkin_date'));
              const end = String(values.get('checkout_date'));
              const departure = String(values.get('departure_time'));
              const editedTime = departure !== (transportData.depTime || '08:30');
              if (!end || end <= start) { setChatError('Дата возвращения должна быть позже даты вылета.'); return; }
              const ok = await handleSendMessage(`Перенеси поездку на ${start} — ${end}${editedTime ? `, вылет в ${departure}` : ''}.`, 'edit_trip',
                { checkin_date: start, checkout_date: end, ...(editedTime ? { departure_time: departure } : {}) });
              if (ok) setIsDateEditorOpen(false);
            }} className="max-w-xl mx-auto bg-white rounded-2xl p-5 mb-4 space-y-4 border border-blue-200">
              <h2 className="text-lg font-bold">Перенести даты и время поездки</h2>
              <p className="text-sm text-gray-600">
                Длительность: {Math.max(1, Math.round((new Date(checkoutDraft) - new Date(dateDraft)) / (1000 * 60 * 60 * 24)) || dateNights)} ноч. Оценка погоды и расписание рейсов обновятся для новых параметров.
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <label className="text-sm font-semibold">Начало поездки
                  <input
                    name="checkin_date"
                    type="date"
                    required
                    min="2000-01-01"
                    max="2100-11-30"
                    value={dateDraft}
                    onChange={e => {
                      const newStart = e.target.value;
                      setDateDraft(newStart);
                      if (checkoutDraft && new Date(checkoutDraft) <= new Date(newStart)) {
                        setCheckoutDraft(shiftedCheckout(newStart, dateNights));
                      }
                    }}
                    className="mt-1 block w-full border border-gray-300 rounded-xl px-3 py-2"
                  />
                </label>
                <label className="text-sm font-semibold">Окончание поездки
                  <input
                    name="checkout_date"
                    type="date"
                    required
                    min={dateDraft || "2000-01-01"}
                    max="2100-11-30"
                    value={checkoutDraft}
                    onChange={e => setCheckoutDraft(e.target.value)}
                    className="mt-1 block w-full border border-gray-300 rounded-xl px-3 py-2"
                  />
                </label>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <label className="text-sm font-semibold">Время вылета
                  <input
                    name="departure_time"
                    type="time"
                    required
                    value={depTimeDraft}
                    onChange={e => setDepTimeDraft(e.target.value)}
                    className="mt-1 block w-full border border-gray-300 rounded-xl px-3 py-2"
                  />
                </label>
                <label className="text-sm font-semibold">Текущий прилёт (пересчитается по рейсу)
                  <input
                    name="arrival_time"
                    type="time"
                    required
                    value={arrTimeDraft}
                    readOnly
                    className="mt-1 block w-full border border-gray-300 rounded-xl px-3 py-2"
                  />
                </label>
              </div>
              {chatError && <p role="alert" className="text-red-700 text-sm">{chatError}</p>}
              <div className="flex gap-2">
                <button type="submit" disabled={isTyping || !checkoutDraft} className="rounded-xl bg-[#1943EB] text-white px-4 py-2 text-sm font-bold disabled:opacity-50">{isTyping ? 'Обновляем поездку…' : 'Применить даты и время'}</button>
                <button type="button" onClick={() => setIsDateEditorOpen(false)} className="rounded-xl bg-gray-100 px-4 py-2 text-sm">Отмена</button>
              </div>
            </form>
          )}
          {!hasPlan ? (
            <div role="status" className="max-w-xl mx-auto rounded-2xl bg-white border border-white p-6 space-y-3">
              <h2 className="text-xl font-bold">{isInitializing ? "Загружаем ваш чат…" : planStatus === "alternatives" ? "Выберите новое направление" : planStatus === "unavailable" ? "Нужны другие условия поездки" : "Ваша поездка начинается здесь"}</h2>
              {travelStyleLabel && <p className="text-sm font-semibold text-gray-700">Тип отдыха: {travelStyleLabel}</p>}
              <p className="text-sm text-gray-700 leading-relaxed">{planMessage || "Расскажите, куда и когда хотите поехать, сколько человек едет и какой у вас бюджет. Я подберу варианты, посчитаю полную стоимость и покажу план здесь."}</p>
              {chatState.date_weather && <div className="rounded-xl bg-blue-50 p-3 text-sm text-gray-700">
                <p className="font-semibold">{chatState.date_weather.source === 'Offline Climate Fallback' ? 'Климатическая оценка' : 'Прогноз погоды'} на {chatState.date_weather.date}</p>
                <p>{chatState.date_weather.temp} · {chatState.date_weather.cond}</p>
              </div>}
              {!["unavailable", "alternatives"].includes(planStatus) && <p className="text-sm text-gray-500">Например: «Хочу к морю вдвоём на неделю, до 150 000 ₽ за всё». Можно начать с быстрых кнопок в чате.</p>}
            </div>
          ) : (
          <div className="w-full max-w-5xl mx-auto space-y-3.5 transition-all duration-300 px-2 sm:px-4">
            {/* РЕЖИМ 1: ОСНОВНОЙ ПЛАН */}
            {(viewMode === 'canvas' || (viewMode === 'compare' && availableOptionKeys.length < 2)) && (
              <>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  {travelStyleLabel && <p className="text-sm font-semibold text-gray-700">Тип отдыха: {travelStyleLabel}</p>}
                </div>
                {/* Переключатель вариантов */}
                <div className={`grid grid-cols-1 ${availableOptionKeys.length > 1 ? 'sm:grid-cols-2' : ''} gap-3 print:hidden`}>
                  {availableOptionKeys.map((key) => {
                    const opt = tripOptions[key];
                    const tData = opt.transport || opt.flight;
                    const total =
                      tData.price +
                      opt.hotel.pricePerNight * opt.hotel.nights +
                      opt.extras.reduce((a, b) => a + b.price, 0);
                    const active = selectedOptionKey === key;

                    return (
                      <button
                        key={key}
                        onClick={() => setSelectedOptionKey(key)}
                        className={`text-left p-3.5 rounded-2xl border cursor-pointer flex items-center justify-between transition shadow-2xs ${
                          active
                            ? 'bg-white border-[#1943EB] ring-2 ring-[#1943EB]/30'
                            : 'bg-white/80 border-white hover:bg-white'
                        }`}
                      >
                        <div>
                          <span className="text-xs font-extrabold text-[#1943EB]">
                            Вариант {key} • {tData.type}
                          </span>
                          <div className="text-sm font-bold text-gray-900 mt-0.5">
                            {opt.title}
                          </div>
                        </div>
                        <div className="text-right pl-2 shrink-0">
                          <div className="text-base font-black text-gray-900">
                            {total.toLocaleString('ru-RU')} ₽
                          </div>
                          <div className="text-[11px] text-gray-400 font-medium">итого</div>
                        </div>
                      </button>
                    );
                  })}
                </div>

                {/* Шапка маршрута + Погода */}
                <div className="grid grid-cols-1 lg:grid-cols-12 gap-3">
                  <div className="lg:col-span-8 bg-white border border-white rounded-2xl p-4 flex flex-col justify-center shadow-xs">
                    <div className="flex flex-wrap items-center gap-2 mb-1">
                      {tripWithPet && currentTrip.hotel.petFriendly && <span className="text-xs bg-emerald-100 text-emerald-800 px-2.5 py-0.5 rounded-md flex items-center gap-1 font-bold">
                        <PawPrint className="w-3.5 h-3.5" /> Pet-friendly 100%
                      </span>}
                      <span className="text-xs text-gray-500 font-semibold">{currentTrip.dates}</span>
                    </div>
                    <h1 className="text-lg sm:text-xl font-black text-gray-900">{currentTrip.title}</h1>
                    <p className="text-xs text-gray-500 flex items-center gap-1 mt-1 font-medium">
                      <MapPin className="w-3.5 h-3.5 text-[#1943EB]" />
                      {currentTrip.destination}
                    </p>
                  </div>

                  <div className="lg:col-span-4 bg-white border border-white rounded-2xl p-4 flex items-center gap-3 shadow-xs print:hidden">
                    <div className="bg-amber-50 border border-amber-200 p-2.5 rounded-xl">
                      <CloudSun className="w-7 h-7 text-amber-500 shrink-0" />
                    </div>
                    <div className="text-xs">
                      <div className="text-gray-400 font-medium">{currentTrip.weather.source === 'Offline Climate Fallback' ? 'Климатическая оценка' : 'Погода в поездке'}</div>
                      <div className="text-sm font-black text-gray-900 mt-0.5">{currentTrip.weather.temp}</div>
                      <div className="text-gray-600 font-medium">{currentTrip.weather.cond}</div>
                    </div>
                  </div>
                </div>

                {/* СРЕДНИЙ РЯД: БИЛЕТ И ОТЕЛЬ СТОЯТ РЯДОМ В 2 КОЛОНКИ НА ПК */}
                <div className="grid grid-cols-1 xl:grid-cols-12 gap-3.5">

                  {/* Карточка билета (5 колонок) */}
                  <div className="xl:col-span-5 bg-white border border-white rounded-2xl p-4 flex flex-col justify-between shadow-xs space-y-3">
                    <div>
                      <div className="flex items-center justify-between gap-2 border-b border-gray-100 pb-2.5 text-xs">
                        <div className="flex items-center gap-1.5 font-bold text-gray-800">
                          {/поезд|ржд/i.test(transportData.type) ? (
                            <Train className="w-4 h-4 text-[#1943EB] shrink-0" />
                          ) : (
                            <Plane className="w-4 h-4 text-blue-600 shrink-0" />
                          )}
                          <span className="truncate">{transportData.carrier}</span>
                        </div>
                        <span className="bg-blue-50 text-[#1943EB] px-2 py-0.5 rounded font-bold text-[10px] shrink-0">Демобилет</span>
                      </div>

                      <div className="text-[11px] text-gray-500 mt-2 font-medium">
                        {transportData.trainNumber}
                      </div>

                      <div className="grid grid-cols-3 items-center gap-2 my-3.5 bg-gray-50 p-3 rounded-xl border border-gray-100">
                        <div>
                          <div className="text-xl font-black text-gray-900">{transportData.depTime}</div>
                          {transportData.departureTimezone && <div className="text-[10px] text-gray-500">UTC{transportData.departureTimezone}</div>}
                          <div className="text-xs font-bold text-gray-800">{transportData.depCity}</div>
                          <div className="text-[10px] text-gray-400 truncate">{transportData.depStation}</div>
                        </div>

                        <div className="text-center px-1">
                          <div className="text-[10px] text-gray-400 font-semibold">{transportData.duration}</div>
                          <div className="border-t-2 border-dashed border-gray-300 my-1.5" />
                          <div className="text-[10px] text-[#1943EB] font-bold">{transportData.connectionLabel || 'Прямой'}</div>
                        </div>

                        <div className="text-right">
                          <div className="text-xl font-black text-gray-900">{transportData.arrTime}</div>
                          {transportData.arrivalTimezone && <div className="text-[10px] text-gray-500">UTC{transportData.arrivalTimezone}</div>}
                          <div className="text-xs font-bold text-gray-800">{transportData.arrCity}</div>
                          <div className="text-[10px] text-gray-400 truncate">{transportData.arrStation}</div>
                        </div>
                      </div>
                    </div>

                    {transportData.legs?.length > 1 && <div className="mb-3 space-y-2 text-xs">
                      {transportData.legs.map((leg,index) => <div key={index} className="rounded-lg border border-blue-100 p-2">
                        <div className="font-semibold">{leg.number}: {leg.from.title} → {leg.to.title}</div>
                        <div>{leg.departure.slice(0,16).replace('T',' ')} → {leg.arrival.slice(0,16).replace('T',' ')}</div>
                        {transportData.layovers?.[index] && <div className="text-blue-700">Пересадка {transportData.layovers[index].minutes} мин{transportData.layovers[index].stationChange ? ', смена станции' : ''}</div>}
                      </div>)}
                    </div>}
                    <p className="text-xs text-gray-500 mb-2">{transportData.scheduleConditional ? 'Условный перенос расписания' : transportData.source || 'Демонстрационное расписание'} · Цена демонстрационная</p>
                    {transportData.returnFlight && (
                      <div className="mb-3 rounded-xl bg-blue-50 p-3 text-xs">
                        <div className="font-bold text-blue-700">Обратно · {transportData.returnFlight.date}</div>
                        {transportData.returnFlight.legs?.length > 1 && <div className="text-xs mt-1">{transportData.returnFlight.legs.map(leg => `${leg.from.title} → ${leg.to.title} (${leg.departure.slice(11,16)}–${leg.arrival.slice(11,16)})`).join(' · ')}</div>}
                        <div className="mt-1 font-semibold text-gray-900">
                          {transportData.arrCity} {transportData.returnFlight.departure_time} → {transportData.depCity} {transportData.returnFlight.arrival_time}
                        </div>
                        <div className="mt-1 text-gray-500">
                          {transportData.returnFlight.flight_number} · Прибытие {transportData.returnFlight.arrival_date}
                        </div>
                      </div>
                    )}
                    <div className="pt-2 border-t border-gray-100 flex items-center justify-between text-xs">
                      <span className="text-gray-500 font-medium truncate pr-2">
                        {transportData.priceIncludesReturn ? 'Туда и обратно · ' : ''}{transportData.wagonOrClass}
                      </span>
                      <span className="font-black text-sm text-gray-900 shrink-0">
                        {transportData.price.toLocaleString('ru-RU')} ₽
                      </span>
                    </div>
                  </div>

                  {/* Карточка отеля (7 колонок) */}
                  <div className="xl:col-span-7 bg-white border border-white rounded-2xl overflow-hidden flex flex-col sm:flex-row shadow-xs">
                    <img
                      src={currentTrip.hotel.image}
                      alt={currentTrip.hotel.name}
                      onError={(e) => {
                        e.currentTarget.onerror = null;
                        e.currentTarget.src = 'https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=900&q=80';
                      }}
                      className="w-full sm:w-48 h-44 sm:h-auto object-cover shrink-0"
                    />
                    <div className="p-4 flex-1 flex flex-col justify-between space-y-2">
                      <div>
                        <div className="flex items-center justify-between text-xs">
                          <span className="text-amber-600 font-bold">
                            {'★'.repeat(currentTrip.hotel.stars)} Отель
                          </span>
                          <span className="bg-[#1943EB] text-white px-2 py-0.5 rounded-md font-bold">
                            ★ {currentTrip.hotel.rating}
                          </span>
                        </div>
                        <h2 className="text-base font-bold text-gray-900 mt-1">
                          {currentTrip.hotel.name}
                        </h2>
                        <p className="text-xs text-gray-400 font-medium line-clamp-1">
                          {currentTrip.hotel.address}
                        </p>

                        <div className="flex flex-wrap gap-1 mt-2">
                          {currentTrip.hotel.tags.map((tag, i) => (
                            <span
                              key={i}
                              className="text-[11px] bg-gray-100 text-gray-700 px-2 py-0.5 rounded font-semibold"
                            >
                              {tag}
                            </span>
                          ))}
                        </div>
                      </div>

                      <div className="pt-2.5 border-t border-gray-100 flex flex-wrap items-center justify-between gap-2 text-xs">
                        <div>
                          {currentTrip.hotel.nights} ноч.: <b className="text-sm font-black">{hotelTotal.toLocaleString('ru-RU')} ₽</b>
                        </div>
                        {tripWithPet && currentTrip.hotel.petFriendly && <span className="text-[#1943EB] font-bold">✓ Pet-friendly номер</span>}
                      </div>
                    </div>
                  </div>

                </div>

                {/* НИЖНИЙ РЯД: ТАЙМЛАЙН И СМЕТА */}
                <div className="grid grid-cols-1 lg:grid-cols-12 gap-3.5">
                  <div className="lg:col-span-7 bg-white border border-white rounded-2xl p-4 sm:p-5 shadow-xs">
                    <h3 className="text-sm font-bold text-gray-900 mb-3.5 flex items-center gap-2">
                      <Clock className="w-4 h-4 text-[#1943EB]" />
                      Расписание поездки (Таймлайн)
                    </h3>
                    <div className="space-y-3 border-l-2 border-[#1943EB] pl-3.5">
                      {currentTrip.timeline.map((item, idx) => (
                        <div key={idx} className="text-xs">
                          <div className="font-bold text-[#1943EB]">{item.time}</div>
                          <div className="font-bold text-gray-900 mt-0.5">{item.title}</div>
                          <div className="text-gray-400 font-medium">{item.desc}</div>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="lg:col-span-5 bg-white border border-white rounded-2xl p-4 sm:p-5 shadow-xs flex flex-col justify-between">
                    <div>
                      <h3 className="text-sm font-bold text-gray-900 mb-3">Итоговая смета</h3>
                      <div className="space-y-2 text-xs">
                        <div className="flex justify-between text-gray-600 font-medium">
                          <span>Транспорт туда-обратно:</span>
                          <span className="font-bold text-gray-900">{transportData.price.toLocaleString('ru-RU')} ₽</span>
                        </div>
                        <div className="flex justify-between text-gray-600 font-medium">
                          <span>Отель ({currentTrip.hotel.nights} ноч.):</span>
                          <span className="font-bold text-gray-900">{hotelTotal.toLocaleString('ru-RU')} ₽</span>
                        </div>
                        {currentTrip.extras.map((ex, i) => (
                          <div key={i} className="flex justify-between text-gray-600 font-medium">
                            <span className="pr-2">{ex.name}:</span>
                            <span className="font-bold text-gray-900 shrink-0">
                              {ex.price === 0 ? '0 ₽' : `${ex.price.toLocaleString('ru-RU')} ₽`}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>

                    <div className="pt-3.5 mt-4 border-t border-gray-100 space-y-3">
                      <div className="flex justify-between items-baseline">
                        <span className="text-xs text-gray-500 font-bold">К оплате:</span>
                        <span className="text-2xl font-black text-gray-900">
                          {grandTotal.toLocaleString('ru-RU')} ₽
                        </span>
                      </div>

                      <button
                        onClick={handleStartCheckout}
                        className="w-full bg-[#1943EB] hover:bg-blue-700 text-white font-bold py-3 px-4 rounded-xl text-sm flex items-center justify-center gap-2 cursor-pointer shadow-sm transition"
                      >
                        <CreditCard className="w-4 h-4" />
                        Оплатить поездку в 1 клик
                      </button>
                    </div>
                  </div>
                </div>
              </>
            )}

            {/* РЕЖИМ 2: СРАВНЕНИЕ */}
            {viewMode === 'compare' && availableOptionKeys.length >= 2 && (
              <div className="space-y-4 print:hidden">
                <div className="bg-white border border-white rounded-2xl p-4 shadow-xs">
                  <div>
                    <h2 className="text-lg font-bold text-gray-900">
                      Интерактивное сравнение: Вариант А vs Вариант Б
                    </h2>
                    <p className="text-xs text-gray-400 font-medium">Вы можете управлять выбором в чате слева или переключить вариант кнопкой ниже</p>
                  </div>
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  {availableOptionKeys.map((key) => {
                    const opt = tripOptions[key];
                    const tData = opt.transport || opt.flight;
                    const optTotal =
                      tData.price +
                      opt.hotel.pricePerNight * opt.hotel.nights +
                      opt.extras.reduce((a, b) => a + b.price, 0);
                    const isSelected = selectedOptionKey === key;

                    return (
                      <div
                        key={key}
                        className={`bg-white rounded-2xl border p-4 sm:p-5 flex flex-col justify-between shadow-xs ${
                          isSelected ? 'border-[#1943EB] ring-2 ring-[#1943EB]/30' : 'border-white'
                        }`}
                      >
                        <div className="space-y-3.5">
                          <div className="flex justify-between items-center border-b border-gray-100 pb-3">
                            <span className="font-bold text-xs bg-blue-50 text-[#1943EB] px-3 py-1 rounded-md">
                              Вариант {key}
                            </span>
                            <span className="font-black text-xl text-gray-900">
                              {optTotal.toLocaleString('ru-RU')} ₽
                            </span>
                          </div>

                          <div>
                            <div className="text-xs text-gray-400 font-semibold">{tData.type}</div>
                            <div className="font-bold text-base text-gray-900 mt-0.5">{opt.hotel.name}</div>
                          </div>

                          <div className="bg-green-50/70 border border-green-200 rounded-xl p-3.5 space-y-2">
                            <div className="text-xs font-black text-green-900 uppercase tracking-wider">Плюсы сборки:</div>
                            {opt.hotel.pros.map((pro, i) => (
                              <div key={i} className="flex items-start gap-2 text-xs text-gray-800 font-medium">
                                <CheckCircle2 className="w-4 h-4 text-green-600 shrink-0 mt-0.5" />
                                <span>{pro}</span>
                              </div>
                            ))}
                          </div>

                          <div className="bg-rose-50/70 border border-rose-200 rounded-xl p-3.5 space-y-2">
                            <div className="text-xs font-black text-rose-900 uppercase tracking-wider">Минусы / Компромиссы:</div>
                            {opt.hotel.cons.map((con, i) => (
                              <div key={i} className="flex items-start gap-2 text-xs text-gray-800 font-medium">
                                <XCircle className="w-4 h-4 text-rose-600 shrink-0 mt-0.5" />
                                <span>{con}</span>
                              </div>
                            ))}
                          </div>
                        </div>

                        <button
                          onClick={() => {
                            setSelectedOptionKey(key);
                            changeViewMode('canvas');
                          }}
                          className="mt-5 w-full bg-[#1943EB] hover:bg-blue-700 text-white py-3 rounded-xl text-xs font-bold cursor-pointer transition shadow-xs"
                        >
                          Выбрать Вариант {key} и перейти к плану
                        </button>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* РЕЖИМ 3: ОПЛАТА */}
            {viewMode === 'checkout' && (
              <div className="max-w-xl mx-auto bg-white border border-white rounded-2xl p-6 sm:p-8 space-y-6 shadow-md print:hidden">
                <div className="flex items-center justify-between border-b border-gray-100 pb-4">
                  <div className="flex items-center gap-2.5">
                    <div className="bg-blue-50 text-[#1943EB] p-2 rounded-xl">
                      <Lock className="w-5 h-5" />
                    </div>
                    <div>
                      <h2 className="text-lg font-black text-gray-900">Безопасная онлайн-оплата</h2>
                      <p className="text-xs text-gray-400 font-medium">Демонстрационное бронирование</p>
                    </div>
                  </div>
                  <button
                    onClick={() => setViewMode('canvas')}
                    className="text-xs text-gray-500 hover:text-gray-900 font-bold cursor-pointer"
                  >
                    Отмена
                  </button>
                </div>

                <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 flex items-center justify-between">
                  <div>
                    <div className="text-xs text-gray-500 font-medium">Сумма к списанию:</div>
                    <div className="text-xl font-black text-gray-900">{grandTotal.toLocaleString('ru-RU')} ₽</div>
                  </div>
                  <div className="text-right text-xs text-[#1943EB] font-bold">
                    ✓ Начислим {loyaltyPoints(grandTotal).toLocaleString('ru-RU')} баллов
                  </div>
                </div>

                <div className="space-y-3">
                  <div className="text-xs font-bold text-gray-700 uppercase tracking-wider">Выберите способ оплаты:</div>
                  <div className="grid grid-cols-3 gap-3">
                    <button
                      onClick={() => setPaymentMethod('sbp')}
                      className={`p-3 rounded-xl border text-xs font-bold flex flex-col items-center gap-1.5 cursor-pointer transition ${
                        paymentMethod === 'sbp' ? 'border-[#1943EB] bg-blue-50/50 text-[#1943EB]' : 'border-gray-200 text-gray-700 hover:bg-gray-50'
                      }`}
                    >
                      <Smartphone className="w-5 h-5" />
                      <span>СБП</span>
                    </button>
                    <button
                      onClick={() => setPaymentMethod('card')}
                      className={`p-3 rounded-xl border text-xs font-bold flex flex-col items-center gap-1.5 cursor-pointer transition ${
                        paymentMethod === 'card' ? 'border-[#1943EB] bg-blue-50/50 text-[#1943EB]' : 'border-gray-200 text-gray-700 hover:bg-gray-50'
                      }`}
                    >
                      <CreditCard className="w-5 h-5" />
                      <span>Карта</span>
                    </button>
                    <button
                      onClick={() => setPaymentMethod('sber')}
                      className={`p-3 rounded-xl border text-xs font-bold flex flex-col items-center gap-1.5 cursor-pointer transition ${
                        paymentMethod === 'sber' ? 'border-[#1943EB] bg-blue-50/50 text-[#1943EB]' : 'border-gray-200 text-gray-700 hover:bg-gray-50'
                      }`}
                    >
                      <ShieldCheck className="w-5 h-5" />
                      <span>SberPay</span>
                    </button>
                  </div>
                </div>

                {paymentMethod === 'card' && (
                  <div className="space-y-3 bg-gray-50 p-4 rounded-xl border border-gray-200">
                    <div>
                      <label className="text-xs text-gray-500 font-bold">Номер карты</label>
                      <input type="text" defaultValue="4276 3800 9921 4410" className="w-full mt-1 bg-white border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono" />
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="text-xs text-gray-500 font-bold">Срок</label>
                        <input type="text" defaultValue="09/29" className="w-full mt-1 bg-white border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono" />
                      </div>
                      <div>
                        <label className="text-xs text-gray-500 font-bold">CVC</label>
                        <input type="password" defaultValue="888" className="w-full mt-1 bg-white border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono" />
                      </div>
                    </div>
                  </div>
                )}

                <button
                  onClick={handleConfirmPayment}
                  disabled={isBookingLoading}
                  className="w-full bg-[#1943EB] hover:bg-blue-700 disabled:bg-gray-400 text-white font-black py-4 px-6 rounded-xl text-base flex items-center justify-center gap-2 cursor-pointer shadow-md transition"
                >
                  {isBookingLoading ? (
                    <>
                      <RefreshCw className="w-5 h-5 animate-spin" />
                      Проводим платеж через банк...
                    </>
                  ) : (
                    <>
                      <Check className="w-5 h-5" />
                      Подтвердить и оплатить {grandTotal.toLocaleString('ru-RU')} ₽
                    </>
                  )}
                </button>
              </div>
            )}

            {/* РЕЖИМ 4: МАРШРУТНЫЙ ЛИСТ */}
            {viewMode === 'itinerary' && (
              <div className="max-w-3xl mx-auto bg-white border border-gray-300 rounded-2xl p-6 sm:p-8 space-y-6 shadow-lg print:border-none print:shadow-none print:p-0 print:max-w-none">

                <div className="flex items-center justify-between border-b border-gray-200 pb-4 print:hidden">
                  <div className="flex items-center gap-2 text-emerald-700 font-bold text-sm">
                    <ShieldCheck className="w-5 h-5" />
                    <span>Электронный документ бронирования</span>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => window.print()}
                      className="bg-[#1943EB] hover:bg-blue-700 text-white text-xs font-bold px-4 py-2.5 rounded-xl flex items-center gap-2 cursor-pointer transition shadow-xs"
                    >
                      <Printer className="w-4 h-4" />
                      Распечатать / Сохранить PDF
                    </button>
                    <button
                      onClick={handleReturnToCanvas}
                      className="bg-gray-100 hover:bg-gray-200 text-gray-800 text-xs font-bold px-4 py-2.5 rounded-xl cursor-pointer transition"
                    >
                      Закрыть
                    </button>
                  </div>
                </div>

                <div className="space-y-6 text-gray-900">

                  <div className="flex justify-between items-start border-b-2 border-gray-900 pb-4">
                    <div>
                      <div className="text-2xl font-black text-[#1943EB]">TravelAIChatbot</div>
                      <div className="text-xs text-gray-500 font-medium">Маршрутный лист и электронный ваучер</div>
                    </div>
                    <div className="text-right">
                      <div className="text-sm font-black">Заказ: {bookingInfo.pnr}</div>
                      <div className="text-xs text-gray-500">Дата оформления: {bookingInfo.issuedAt || todayISO}</div>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-xs bg-gray-50 p-4 rounded-xl border border-gray-200 print:bg-white print:border-gray-900">
                    <div>
                      <span className="text-gray-500 block">Статус:</span>
                      <span className="font-bold text-emerald-700">Оплачено / Подтверждено</span>
                    </div>
                    <div>
                      <span className="text-gray-500 block">Ваучер отеля:</span>
                      <span className="font-bold">{bookingInfo.voucherId}</span>
                    </div>
                    <div>
                      <span className="text-gray-500 block">Пассажиры:</span>
                      <span className="font-bold">
                        {partyLabel(bookingInfo.travellers || party)}
                      </span>
                    </div>
                    <div>
                      <span className="text-gray-500 block">Итоговая сумма:</span>
                      <span className="font-bold">{grandTotal.toLocaleString('ru-RU')} ₽</span>
                    </div>
                  </div>

                  <div className="space-y-3">
                    <h3 className="text-sm font-black uppercase tracking-wider text-gray-800 border-b border-gray-200 pb-1">
                      Детали маршрута и таймлайн
                    </h3>
                    <div className="space-y-2">
                      {currentTrip.timeline.map((step, i) => (
                        <div key={i} className="flex justify-between items-center text-xs py-1.5 border-b border-gray-100">
                          <div>
                            <span className="font-bold text-[#1943EB] mr-2">{step.time}</span>
                            <span className="font-bold">{step.title}</span>
                            <div className="text-gray-500 text-[11px]">{step.desc}</div>
                          </div>
                          <span className="font-bold text-gray-700 shrink-0">Подтверждено</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="pt-6 border-t border-gray-200 flex justify-between items-center text-xs text-gray-500">
                    <div>
                      <p>Демонстрационный ваучер поездки.</p>
                    </div>
                    <div className="font-mono text-sm font-bold text-gray-900 tracking-widest">
                      ||| | ||| || || | |||
                    </div>
                  </div>

                </div>
              </div>
            )}

          </div>
          )}
        </main>
      </div>
    </div>
  );
}
