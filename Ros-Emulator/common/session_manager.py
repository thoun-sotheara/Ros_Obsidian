from dataclasses import dataclass, field
import threading


Address = tuple[str, int]


@dataclass
class PlayerSession:
    username: str
    role_id: int
    client_addr: Address
    blowfish_key: bytes
    reply_id: int
    connection_state: str = "LOGIN_ACCEPTED"
    room_id: str | None = None
    login_addr: Address | None = None
    metadata: dict = field(default_factory=dict)


class SessionManager:
    """Thread-safe in-memory session registry shared by LoginApp and BaseApp."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_address: dict[Address, PlayerSession] = {}
        self._by_reply_id: dict[int, PlayerSession] = {}
        self._by_username: dict[str, PlayerSession] = {}
        self._by_identity: dict[tuple[str, int], PlayerSession] = {}

    def register(
        self,
        username: str,
        role_id: int,
        client_addr: Address,
        blowfish_key: bytes,
        reply_id: int,
    ) -> PlayerSession:
        session = PlayerSession(
            username=username.strip().lower(),
            role_id=int(role_id),
            client_addr=client_addr,
            blowfish_key=bytes(blowfish_key),
            reply_id=reply_id & 0xFFFFFFFF,
            login_addr=client_addr,
        )
        with self._lock:
            previous = self._by_username.get(session.username)
            if previous is not None:
                self._remove_session(previous)
            self._by_address[client_addr] = session
            self._by_reply_id[session.reply_id] = session
            self._by_username[session.username] = session
            self._by_identity[(session.username, session.role_id)] = session
        return session

    def get_by_address(self, address: Address) -> PlayerSession | None:
        with self._lock:
            return self._by_address.get(address)

    def get_by_reply_id(self, reply_id: int) -> PlayerSession | None:
        with self._lock:
            return self._by_reply_id.get(reply_id & 0xFFFFFFFF)

    def get_by_username(self, username: str) -> PlayerSession | None:
        with self._lock:
            return self._by_username.get(username.strip().lower())

    def get_by_identity(self, username: str, role_id: int) -> PlayerSession | None:
        with self._lock:
            return self._by_identity.get((username.strip().lower(), int(role_id)))

    def bind_baseapp(self, session: PlayerSession, address: Address) -> None:
        with self._lock:
            self._by_address[address] = session
            session.client_addr = address
            session.connection_state = "BASEAPP_CONNECTED"

    def set_room(self, session: PlayerSession, room_id: str | None) -> None:
        with self._lock:
            session.room_id = room_id

    def active_sessions(self) -> list[PlayerSession]:
        with self._lock:
            return list(self._by_username.values())

    def remove(self, session: PlayerSession) -> None:
        with self._lock:
            self._remove_session(session)

    def _remove_session(self, session: PlayerSession) -> None:
        for address, candidate in list(self._by_address.items()):
            if candidate is session:
                del self._by_address[address]
        if self._by_reply_id.get(session.reply_id) is session:
            del self._by_reply_id[session.reply_id]
        if self._by_username.get(session.username) is session:
            del self._by_username[session.username]
        identity = (session.username, session.role_id)
        if self._by_identity.get(identity) is session:
            del self._by_identity[identity]


SESSION_MANAGER = SessionManager()
