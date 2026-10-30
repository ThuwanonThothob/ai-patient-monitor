"use client";

import { useEffect, useRef, useState, type FormEvent } from 'react';
import { usePatientResource } from './usePatientResource';
import { notifyNewChat } from './chatNotify';
import { requestJson } from './apiRequest';
import s from './CareChat.module.css';
import NotificationPanel from './NotificationPanel';

type ChatMessage = {
  id: number;
  sender: 'staff' | 'patient';
  sender_display_name: string;
  message: string;
  created_at: number;
  read: boolean;
};

type Participant = {
  subject: string;
  display_name: string;
  role: string;
};

type ChatRoom = {
  patient_id: string;
  patient_display_name: string;
  participants: {
    patient: Participant;
    care_team: Participant;
    assignment: { care_setting: string };
  };
  messages: ChatMessage[];
  notice: string;
};

type Conversation = {
  patient_id: string;
  patient_display_name: string;
  message: string;
  created_at: number | null;
  unread: number;
};

type Draft = {
  text: string;
  clientKey: string;
};

function time(value: number) {
  return new Date(value * 1000).toLocaleString('th-TH', {
    dateStyle: 'short',
    timeStyle: 'short',
  });
}

function newClientKey() {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), value =>
    value.toString(16).padStart(2, '0')
  ).join('');
}

const AVATAR_PALETTE = [
  '#0084ff',
  '#00a884',
  '#6b52ae',
  '#d93f6c',
  '#e56b00',
  '#0097a7',
  '#43a047',
  '#5c6bc0',
];

function getInitials(name: string): string {
  if (!name) return '?';
  const clean = name.trim();
  const parts = clean.split(/\s+/);
  if (parts.length >= 2) {
    const first = parts[0].charAt(0);
    const second = parts[1].charAt(0);
    return (first + second).toUpperCase();
  }
  return clean.slice(0, 2).toUpperCase();
}

function getAvatarColor(identifier: string): string {
  let hash = 0;
  for (let i = 0; i < identifier.length; i++) {
    hash = (hash << 5) - hash + identifier.charCodeAt(i);
    hash |= 0;
  }
  return AVATAR_PALETTE[Math.abs(hash) % AVATAR_PALETTE.length];
}

const patientQuickChat = [
  'ได้รับข้อมูลแผนการดูแลแล้ว ขอบคุณครับ/ค่ะ',
  'รบกวนสอบถามเวลาตรวจเยี่ยมรอบถัดไปครับ/ค่ะ',
  'อุปกรณ์วัดสัญญาณชีพขึ้นรอข้อมูลใหม่ รบกวนช่วยดูให้หน่อยครับ/ค่ะ',
];

export default function CareChat({
  staff = false,
  openPatient,
}: {
  staff?: boolean;
  openPatient?: (id: string) => void;
}) {
  const conversations = usePatientResource<{ conversations: Conversation[] }>(
    staff ? '/api/care-chat/conversations' : null,
    5000,
    true
  );
  const [selected, setSelected] = useState('');
  const [search, setSearch] = useState('');
  const [filterTab, setFilterTab] = useState<'all' | 'unread'>('all');
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const previousUnread = useRef<number | null>(null);
  const unread =
    conversations.data?.conversations.reduce((sum, item) => sum + item.unread, 0) ?? 0;

  useEffect(() => {
    if (unread === undefined) return;
    if (staff && previousUnread.current !== null && unread > previousUnread.current) {
      notifyNewChat('ผู้ป่วย');
    }
    previousUnread.current = unread;
  }, [staff, unread]);

  const selectedPatient = conversations.data?.conversations.some(
    item => item.patient_id === selected
  )
    ? selected
    : '';
  const roomKey = staff ? selectedPatient : 'me';

  const chat = roomKey ? (
    <ChatRoomPanel
      key={roomKey}
      staff={staff}
      selectedPatient={selectedPatient}
      draft={drafts[roomKey] ?? { text: '', clientKey: '' }}
      setDraft={draft =>
        setDrafts(previous => ({ ...previous, [roomKey]: draft }))
      }
      afterSend={conversations.refresh}
      openPatient={openPatient}
      onBack={staff ? () => setSelected('') : undefined}
    />
  ) : (
    <section className={s.chat + ' ' + s.chooseRoom}>
      <div className={s.avatarWrapper}>
        <div className={s.avatar} style={{ background: '#0084ff', margin: '0 auto' }}>
          💬
        </div>
      </div>
      <h2>เลือกผู้ป่วยเพื่อเปิดบทสนทนา</h2>
      <p>ค้นหาชื่อหรือรหัสผู้ป่วยจากรายการ แล้วตรวจชื่อผู้รับก่อนส่งข้อความ</p>
    </section>
  );

  if (!staff) return chat;

  const conversationList = conversations.data?.conversations ?? [];
  const filtered = conversationList.filter(item => {
    if (filterTab === 'unread' && item.unread === 0) return false;
    if (!search.trim()) return true;
    return (item.patient_id + ' ' + item.patient_display_name)
      .toLowerCase()
      .includes(search.trim().toLowerCase());
  });

  return (
    <div className={s.staffLayout}>
      <aside className={s.rooms}>
        <div className={s.sidebarHeader}>
          <h2>
            แชทผู้ป่วย
            {unread > 0 ? <span className={s.unreadPill}>{unread} ใหม่</span> : null}
          </h2>
          <button
            type="button"
            className={s.sidebarRefreshBtn}
            onClick={conversations.refresh}
            disabled={conversations.loading}
          >
            ↻ รีเฟรช
          </button>
        </div>

        <div className={s.filterTabs} role="tablist" aria-label="ตัวกรองบทสนทนา">
          <button
            type="button"
            role="tab"
            aria-selected={filterTab === 'all'}
            className={`${s.filterTab} ${filterTab === 'all' ? s.filterTabActive : ''}`}
            onClick={() => setFilterTab('all')}
          >
            ทั้งหมด
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={filterTab === 'unread'}
            className={`${s.filterTab} ${filterTab === 'unread' ? s.filterTabActive : ''}`}
            onClick={() => setFilterTab('unread')}
          >
            ยังไม่อ่าน {unread > 0 ? `(${unread})` : ''}
          </button>
        </div>

        <div className={s.searchWrapper}>
          <label className={s.searchLabel} htmlFor="chat-search">
            ค้นหาคู่สนทนา
          </label>
          <input
            className={s.search}
            id="chat-search"
            value={search}
            onChange={event => setSearch(event.target.value)}
            placeholder="ค้นหาชื่อหรือรหัสผู้ป่วย…"
          />
        </div>

        {conversations.loading && !conversations.data && (
          <p className={s.loadingText} role="status">กำลังโหลดรายชื่อ…</p>
        )}
        {conversations.error && (
          <p role="alert" className={s.error}>{conversations.error}</p>
        )}
        {conversations.data && filtered.length === 0 && (
          <p className={s.empty}>
            {filterTab === 'unread'
              ? 'ไม่มีข้อความที่ยังไม่อ่าน'
              : search
              ? 'ไม่พบชื่อหรือรหัสที่ค้นหา'
              : 'ยังไม่มีผู้ป่วยที่สามารถติดต่อได้'}
          </p>
        )}

        <div className={s.roomList}>
          {filtered.map(item => {
            const isSelected = selectedPatient === item.patient_id;
            const hasDraft = Boolean(drafts[item.patient_id]?.text);
            const snippet = hasDraft
              ? 'มีข้อความร่างที่ยังไม่ส่ง'
              : item.message || 'ยังไม่มีข้อความ';
            const initials = getInitials(item.patient_display_name || item.patient_id);
            const avatarBg = getAvatarColor(item.patient_id);

            return (
              <button
                type="button"
                key={item.patient_id}
                className={`${s.roomItem} ${isSelected ? s.roomItemActive : ''}`}
                aria-pressed={isSelected}
                onClick={() => setSelected(item.patient_id)}
              >
                <div className={s.avatarWrapper}>
                  <div className={s.avatar} style={{ background: avatarBg }}>
                    {initials}
                  </div>
                  <span className={s.activeBadge} title="พร้อมติดต่อ / ใช้งานอยู่" />
                </div>
                <div className={s.roomDetails}>
                  <div className={s.roomTitleRow}>
                    <strong className={s.roomName}>{item.patient_display_name}</strong>
                    {item.created_at ? (
                      <span className={s.roomTime}>{time(item.created_at)}</span>
                    ) : null}
                  </div>
                  <div className={s.roomSubtitleRow}>
                    <span className={`${s.roomSnippet} ${hasDraft ? s.roomDraft : ''}`}>
                      {hasDraft ? '✏️ ' : ''}{snippet}
                    </span>
                    {item.unread > 0 && (
                      <span className={s.unreadBadge} aria-label={`ยังไม่อ่าน ${item.unread}`}>
                        {item.unread}
                      </span>
                    )}
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </aside>
      {chat}
    </div>
  );
}

function ChatRoomPanel({
  staff,
  selectedPatient,
  draft,
  setDraft,
  afterSend,
  openPatient,
  onBack,
}: {
  staff: boolean;
  selectedPatient: string;
  draft: Draft;
  setDraft: (draft: Draft) => void;
  afterSend: () => void;
  openPatient?: (id: string) => void;
  onBack?: () => void;
}) {
  const endpoint = staff
    ? '/api/care-chat/' + encodeURIComponent(selectedPatient)
    : '/api/me/chat';
  const room = usePatientResource<ChatRoom>(endpoint, 4000, true, true);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [sendError, setSendError] = useState('');
  const [showPush, setShowPush] = useState(false);
  const sending = useRef(false);
  const request = useRef<AbortController | null>(null);
  const list = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const followLatest = useRef(true);

  useEffect(() => () => request.current?.abort(), []);

  useEffect(() => {
    if (list.current && followLatest.current) {
      list.current.scrollTop = list.current.scrollHeight;
    }
  }, [room.data?.messages.length]);

  async function send(event: FormEvent) {
    event.preventDefault();
    const body = draft.text.trim();
    if (!body || sending.current || !room.data) return;
    sending.current = true;
    setBusy(true);
    setNotice('');
    setSendError('');

    const clientKey = draft.clientKey || newClientKey();
    setDraft({ ...draft, clientKey });
    const abort = new AbortController();
    request.current = abort;

    try {
      await requestJson(endpoint, {
        method: 'POST',
        signal: abort.signal,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: body, client_key: clientKey }),
      });
      if (abort.signal.aborted) return;
      setDraft({ text: '', clientKey: '' });
      setNotice('ส่งข้อความแล้ว');
      followLatest.current = true;
      room.refresh();
      afterSend();
    } catch (error) {
      if (!abort.signal.aborted) {
        setSendError(
          (error instanceof Error ? error.message : 'เชื่อมต่อไม่สำเร็จ') +
            ' · ข้อความยังอยู่ กดส่งอีกครั้งได้'
        );
      }
    } finally {
      if (!abort.signal.aborted) {
        sending.current = false;
        setBusy(false);
      }
    }
  }

  const contactName = staff
    ? room.data?.patient_display_name ?? selectedPatient
    : room.data?.participants.care_team.display_name ?? 'ทีมแพทย์และพยาบาล';

  const avatarIdentifier = staff
    ? selectedPatient || 'patient'
    : room.data?.participants.care_team.display_name || 'care-team';

  const avatarInitials = getInitials(
    staff
      ? room.data?.patient_display_name || selectedPatient || 'PT'
      : room.data?.participants.care_team.display_name || 'ทีมดูแล'
  );

  return (
    <section className={s.chat} aria-label="บทสนทนากับทีมดูแล">
      <header className={s.chatHeader}>
        <div className={s.headerProfile}>
          {onBack && (
            <button
              type="button"
              className={s.backBtn}
              onClick={onBack}
              aria-label="กลับไปหน้ารายชื่อคู่สนทนา"
            >
              ← รายชื่อ
            </button>
          )}
          <div className={s.avatarWrapper}>
            <div
              className={s.avatar}
              style={{ background: getAvatarColor(avatarIdentifier) }}
            >
              {avatarInitials}
            </div>
            <span className={s.activeBadge} title="พร้อมติดต่อ / ใช้งานอยู่" />
          </div>
          <div className={s.headerMeta}>
            <h2 className={s.headerTitle}>{contactName}</h2>
            <div className={s.headerStatus}>
              <span className={s.statusDot} />
              <span>พร้อมติดต่อ / ใช้งานอยู่</span>
              {staff && selectedPatient && (
                <span className={s.patientIdTag}>· ID: {selectedPatient}</span>
              )}
            </div>
          </div>
        </div>
        <div className={s.headerActions}>
          {staff && openPatient && room.data?.patient_id && (
            <button
              type="button"
              className={s.headerBtn}
              onClick={() => openPatient(room.data!.patient_id)}
            >
              ดูโปรไฟล์และสัญญาณชีพ
            </button>
          )}
          <button
            type="button"
            className={s.headerBtn}
            onClick={room.refresh}
            disabled={room.loading}
          >
            ↻ โหลดใหม่
          </button>
          <button
            type="button"
            className={s.headerBtn}
            onClick={() => setShowPush(value => !value)}
          >
            ตั้งค่าแจ้งเตือนมือถือ
          </button>
        </div>
      </header>

      <div className={s.chatMetaStrip}>
        <p className={s.warning}>
          ช่องทางติดตามทั่วไป ไม่ใช่ช่องทางฉุกเฉิน หากมีอาการรุนแรงให้ติดต่อ 1669 หรือช่องทางฉุกเฉินของพื้นที่ทันที
        </p>
        <p className={s.syncState} role="status">
          {room.error
            ? 'การเชื่อมต่อขัดข้อง · ประวัติที่แสดงอาจยังไม่ล่าสุด'
            : room.updatedAt
            ? 'อัปเดต ' +
              new Date(room.updatedAt).toLocaleTimeString('th-TH') +
              ' · ตรวจข้อความใหม่อัตโนมัติ'
            : 'กำลังเชื่อมต่อบทสนทนา…'}
        </p>
      </div>

      <details className={s.learnMoreDrawer}>
        <summary className={s.learnMoreSummary}>
          <span>👥 ข้อมูลผู้เข้าร่วมบทสนทนาและความเป็นส่วนตัว (Learn More)</span>
          <span className={s.learnMoreBadge}>ดูข้อมูลห้องแชท</span>
        </summary>
        <div className={s.learnMoreBody}>
          {room.data && (
            <div className={s.participants}>
              <article className={s.participantCard}>
                <small>{staff ? 'ผู้ป่วยที่ได้รับมอบหมาย' : 'โปรไฟล์ของคุณ'}</small>
                <b>{room.data.participants.patient.display_name}</b>
                <span>
                  {room.data.participants.patient.subject} ·{' '}
                  {room.data.participants.assignment.care_setting}
                </span>
              </article>
              <article className={s.participantCard}>
                <small>
                  {staff ? 'ทีมดูแลในบทสนทนานี้' : 'แพทย์/ทีมดูแลที่ได้รับมอบหมาย'}
                </small>
                <b>{room.data.participants.care_team.display_name}</b>
                <span>
                  {room.data.participants.care_team.role} ·{' '}
                  {room.data.participants.care_team.subject}
                </span>
              </article>
            </div>
          )}
          <small className={s.privacy}>
            ข้อความไม่ส่งเข้า Gemini และไม่ใช้ฝึกโมเดล · เปิดการแจ้งเตือนมือถือด้านบนเพื่อรับข้อความขณะปิดแอป เมื่อออกจากระบบจะหยุดส่ง และต้องผูกอุปกรณ์ใหม่เมื่อเข้าสู่ระบบอีกครั้ง
          </small>
        </div>
      </details>

      <div
        ref={list}
        className={s.messages}
        role="log"
        aria-label="ข้อความล่าสุด"
        aria-live="polite"
        aria-relevant="additions"
        onScroll={() => {
          const element = list.current;
          if (element) {
            followLatest.current =
              element.scrollHeight - element.scrollTop - element.clientHeight < 90;
          }
        }}
      >
        {room.loading && !room.data && (
          <p className={s.loadingText}>กำลังโหลดบทสนทนา…</p>
        )}
        {room.error && <p role="alert" className={s.error}>{room.error}</p>}
        {room.data?.messages.length === 0 && (
          <p className={s.empty}>ยังไม่มีข้อความ เริ่มบทสนทนาได้ด้านล่าง</p>
        )}
        {room.data?.messages.length === 100 && (
          <small className={s.syncState}>แสดง 100 ข้อความล่าสุด</small>
        )}
        {room.data?.messages.map(item => {
          const mine = staff ? item.sender === 'staff' : item.sender === 'patient';
          const senderColor = getAvatarColor(item.sender_display_name || item.sender);
          const senderInitials = getInitials(
            item.sender_display_name || (item.sender === 'staff' ? 'แพทย์' : 'ผู้ป่วย')
          );

          return (
            <div key={item.id} className={mine ? s.rowMine : s.rowOther}>
              {!mine && (
                <div
                  className={s.avatarSmall}
                  style={{ background: senderColor }}
                  title={item.sender_display_name}
                >
                  {senderInitials}
                </div>
              )}
              <div className={mine ? s.bubbleMine : s.bubbleOther}>
                {!mine && <b className={s.senderName}>{item.sender_display_name}</b>}
                <p className={s.bubbleText}>{item.message}</p>
                <div className={mine ? s.bubbleMetaMine : s.bubbleMetaOther}>
                  <span>{time(item.created_at)}</span>
                  {mine && (
                    <span>{item.read ? ' · อ่านแล้ว ✓✓' : ' · ส่งแล้ว ✓'}</span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {!staff && (
        <div className={s.quickSection}>
          <small className={s.quickLabel}>
            ข้อความแชทด่วนสำหรับผู้ป่วย (แตะเพื่อเลือกข้อความแล้วกดส่ง):
          </small>
          <div
            className={s.quickRow}
            role="group"
            aria-label="ข้อความแชทด่วนสำหรับผู้ป่วย"
          >
            {patientQuickChat.map(text => (
              <button
                type="button"
                key={text}
                className={s.quickPill}
                disabled={busy || !room.data}
                onClick={() => {
                  setDraft({ text, clientKey: '' });
                  setSendError('');
                  setNotice('');
                  composerRef.current?.focus();
                }}
              >
                {text}
              </button>
            ))}
          </div>
        </div>
      )}

      <form onSubmit={send} className={s.composerArea}>
        <div className={s.composerPill}>
          <textarea
            ref={composerRef}
            id={staff ? 'staff-chat' : 'patient-chat'}
            aria-label={staff ? 'ส่งถึงผู้ป่วย' : 'ส่งถึงทีมดูแล'}
            value={draft.text}
            onChange={event => {
              setDraft({ text: event.target.value, clientKey: '' });
              setSendError('');
              setNotice('');
            }}
            onKeyDown={event => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                if (draft.text.trim() && !busy && room.data) {
                  void send(event);
                }
              }
            }}
            maxLength={2000}
            rows={1}
            className={s.composerInput}
            placeholder={
              staff
                ? 'พิมพ์ข้อความถึงผู้ป่วย… (กด Enter เพื่อส่ง, Shift+Enter เพื่อขึ้นบรรทัดใหม่)'
                : 'พิมพ์ข้อความถึงทีมดูแล… (กด Enter เพื่อส่ง)'
            }
            disabled={busy || !room.data}
          />
          <button
            type="submit"
            className={s.sendBtn}
            aria-label="ส่งข้อความ"
            disabled={busy || !draft.text.trim() || !room.data}
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="currentColor"
              aria-hidden="true"
            >
              <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
            </svg>
          </button>
        </div>
        <div className={s.composerMeta}>
          <span>{draft.text.length}/2,000 ตัวอักษร</span>
          <span>กด Enter เพื่อส่ง · Shift+Enter เพื่อขึ้นบรรทัดใหม่</span>
        </div>
      </form>

      {notice && <p role="status" className={s.notice}>{notice}</p>}
      {sendError && <p role="alert" className={s.error}>{sendError}</p>}

      <details
        open={showPush}
        onToggle={event => setShowPush(event.currentTarget.open)}
        className={s.pushDetails}
      >
        <summary>แจ้งเตือนบนมือถือ / ขณะปิดแอป</summary>
        {showPush && <NotificationPanel patient={!staff} />}
      </details>
    </section>
  );
}
