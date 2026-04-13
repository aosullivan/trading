# Portfolio Management Module -- Design

## Context

The app is a local Flask + vanilla JS desktop tool (PyWebView). It has charting, backtesting, and watchlist features but no connection to real brokerage accounts. This design adds a unified portfolio management section connecting to Vanguard, Fidelity, Schwab, and Robinhood across brokerage, 401k, and IRA account types.

---

## 1. Broker API Reality Check

| Broker | Official API? | Recommended Adapter | Capabilities | Fallback |
|---|---|---|---|---|
| **Schwab** | Yes (OAuth 2.0, from TD Ameritrade) | Direct via `schwab-py` | Positions, balances, **orders** | Plaid (read-only) |
| **Robinhood** | No | SnapTrade aggregator | Positions, balances, **orders** | `robin_stocks` (fragile) or manual |
| **Fidelity** | No | Plaid | Positions, balances (read-only) | Manual CSV/OFX import |
| **Vanguard** | No | Plaid | Positions, balances (read-only) | Manual CSV/OFX import |

**Key constraint:** 401k accounts are always read-only regardless of broker -- rebalancing must go through the employer portal. The system generates human-readable instructions for those.

---

## 2. Secure Credential Storage

**New file:** `lib/credential_store.py`

**Primary: OS Keychain** via `keyring` library (macOS Keychain / Windows Credential Manager)
- Service name: `TriedingView` (matches existing `APP_NAME` in `lib/paths.py`)
- Per-broker entries: `schwab_oauth_token`, `plaid_access_token`, `snaptrade_secret`
- OAuth tokens stored as JSON blobs (access + refresh + expiry)

**Fallback: Encrypted file** at `get_user_data_path("credentials.enc")`
- `cryptography.fernet` with PBKDF2-derived key (100k+ iterations)
- Passphrase requested once at startup via PyWebView dialog, held in memory only

```python
class CredentialStore(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...
    def delete(self, key: str) -> None: ...

class KeyringStore: ...      # Primary
class EncryptedFileStore: ... # Fallback

def get_credential_store() -> CredentialStore:
    # Try keyring, fall back to encrypted file
```

**New deps:** `keyring`, `cryptography`

---

## 3. Broker Adapter Abstraction

**New directory:** `lib/brokers/`

### Core data models (`lib/brokers/base.py`)

```python
@dataclass
class Account:
    id: str
    broker: str              # "schwab", "fidelity", "vanguard", "robinhood"
    name: str
    account_type: str        # "brokerage", "ira_traditional", "ira_roth", "401k"
    capabilities: set        # {"read_positions", "read_balances", "place_orders"}

@dataclass
class Position:
    symbol: str
    quantity: float
    cost_basis: float | None
    market_value: float
    current_price: float
    unrealized_pnl: float | None
    account_id: str
    asset_type: str          # "equity", "etf", "mutual_fund", "option", "bond", "cash"

@dataclass
class Balance:
    account_id: str
    total_value: float
    cash_available: float
    buying_power: float | None

@dataclass
class OrderRequest:
    symbol: str
    side: str                # "buy", "sell"
    quantity: float
    order_type: str          # "market", "limit"
    limit_price: float | None
    account_id: str
```

### Adapter protocol

```python
class BrokerAdapter(Protocol):
    broker_name: str
    def authenticate(self, credential_store) -> bool
    def get_accounts(self) -> list[Account]
    def get_positions(self, account_id: str) -> list[Position]
    def get_balances(self, account_id: str) -> Balance
    def place_order(self, order: OrderRequest) -> OrderResult
    def supports_trading(self, account_id: str) -> bool
    def refresh_auth(self) -> bool
```

### Adapter implementations

| File | Broker(s) | Notes |
|---|---|---|
| `lib/brokers/schwab.py` | Schwab | Direct OAuth 2.0 via `schwab-py` |
| `lib/brokers/plaid.py` | Fidelity, Vanguard | Read-only via Plaid Link |
| `lib/brokers/snaptrade.py` | Robinhood | Positions + orders via SnapTrade |
| `lib/brokers/manual.py` | Any | CSV/OFX file import for unsupported accounts |

### Registry (`lib/brokers/__init__.py`)

```python
ADAPTER_REGISTRY: dict[str, type[BrokerAdapter]] = {
    "schwab": SchwabAdapter,
    "plaid": PlaidAdapter,
    "snaptrade": SnapTradeAdapter,
    "manual": ManualAdapter,
}
```

**New deps:** `schwab-py`, `plaid-python`, `snaptrade-python-sdk`

---

## 4. Account Configuration

**Stored at:** `get_user_data_path("accounts.json")` (same pattern as `watchlist.json`)

```json
{
  "accounts": [
    {
      "id": "schwab-brokerage-1",
      "broker": "schwab",
      "adapter": "schwab",
      "name": "Schwab Individual",
      "account_type": "brokerage",
      "broker_account_id": "12345678",
      "enabled": true
    },
    {
      "id": "fidelity-401k",
      "broker": "fidelity",
      "adapter": "plaid",
      "name": "Fidelity 401k",
      "account_type": "401k",
      "plaid_item_id": "item_abc123",
      "enabled": true
    }
  ]
}
```

The `adapter` field decouples broker identity from integration method. Fidelity positions come through Plaid, but the user sees "Fidelity 401k."

### Account type capabilities

| Type | Can Trade via API? | Rebalancing |
|---|---|---|
| Brokerage | Yes (Schwab, Robinhood) | Direct order placement |
| IRA (Trad/Roth) | Yes (same API access) | Direct order placement |
| 401k | Never | Human-readable instructions only |

---

## 5. API Endpoints

**New blueprint:** `routes/accounts.py`

```
# Account management
GET    /api/accounts                    -- List all configured accounts + connection status
POST   /api/accounts                    -- Add/configure an account
DELETE /api/accounts/<id>               -- Remove an account
POST   /api/accounts/sync              -- Trigger manual refresh of all accounts

# Position data
GET    /api/accounts/<id>/positions     -- Positions for one account
GET    /api/accounts/<id>/balances      -- Balances for one account
GET    /api/positions                   -- Unified positions across ALL accounts

# Portfolio intelligence
GET    /api/allocations                 -- Allocation breakdown (asset class, sector, account type)
GET    /api/rebalance/suggestions       -- Target vs actual, suggested trades per account

# Order management
POST   /api/orders                      -- Submit order (trade-capable accounts only)
GET    /api/orders/history              -- Order audit log

# Auth flows
GET    /api/accounts/auth/schwab        -- Initiate Schwab OAuth
GET    /callback/schwab                 -- OAuth callback handler
POST   /api/accounts/auth/plaid/token   -- Exchange Plaid Link public token
POST   /api/accounts/import             -- CSV/OFX file upload
```

---

## 6. Portfolio Manager (Aggregation Layer)

**New file:** `lib/portfolio_manager.py`

Sits above the broker adapters and provides:

1. **Unified position view** -- Merge positions from all accounts, group by symbol, compute cross-account totals
2. **Allocation analysis** -- % by asset class, sector (via yfinance ticker info from existing `lib/cache.py`), and account type (taxable vs tax-deferred)
3. **Rebalancing engine** -- Given target allocation weights, compute suggested trades per account respecting capabilities:
   - Trade-capable accounts: concrete `OrderRequest` objects
   - 401k accounts: text instructions ("Move 5% from VFIAX to VBTLX via employer portal")
4. **Position caching** -- Store last-known positions in `get_user_data_path("positions_cache.json")` for instant UI load (same stale-while-revalidate pattern used in watchlist routes)

---

## 7. Frontend Design

**New template:** `templates/accounts.html`
**New JS:** `static/js/accounts.js`, `static/js/accounts_auth.js`, `static/js/accounts_charts.js`
**New partials:** `templates/partials/account_card.html`, `templates/partials/allocation_chart.html`

### Page layout

```
+-------------------------------------------------+
|  Nav: Chart | Backtest | Portfolio | [Accounts]  |
+-------------------------------------------------+
|  Connection status bar (per broker, last sync)   |
+------------+------------+-----------------------+
| Total Value| Day Change | Cash Available         |
| $XXX,XXX   | +$X,XXX   | $XX,XXX               |
+------------+------------+-----------------------+
|  Allocation donuts: [By Asset] [By Acct Type]    |
|  [By Sector] [By Broker]                         |
+-------------------------------------------------+
|  Unified Positions Table (sortable)              |
|  Symbol | Qty | Price | Value | P&L | Account    |
|  AAPL   | 50  | 189   | 9450  | +12% | Schwab   |
|  VTI    | 100 | 245   | 24500 | +8%  | Fidelity |
|  ...                                             |
+-------------------------------------------------+
|  > Schwab Individual (Brokerage) -- $XX,XXX     |
|  > Fidelity 401k -- $XX,XXX                     |
|  > Vanguard IRA -- $XX,XXX                      |
|  > Robinhood (Brokerage) -- $XX,XXX             |
+-------------------------------------------------+
|  Rebalancing Panel                               |
|  Target vs Actual | Suggested Trades | Execute   |
+-------------------------------------------------+
|  Settings: Connect/Disconnect | Import CSV       |
+-------------------------------------------------+
```

### UI patterns to reuse from existing code
- Dark theme CSS variables from `static/styles.css`
- Stats card grid (`.pf-stats-grid` class from portfolio.html)
- Table styling (`.ttbl` class)
- Stale-while-revalidate data loading (watchlist pattern)
- SSE streaming for long sync operations

---

## 8. OAuth Flow for Local Desktop App

**Problem:** OAuth requires a callback URL, but the app uses a dynamic port.

**Solution:** Dedicated fixed-port callback listener.

1. User clicks "Connect Schwab" in the UI
2. Backend generates auth URL with random `state` parameter (CSRF protection)
3. Backend spins up a temporary HTTP listener on fixed port `127.0.0.1:17723`
4. User's browser opens, they authenticate with Schwab
5. Schwab redirects to `http://127.0.0.1:17723/callback/schwab?code=...&state=...`
6. Callback handler validates `state`, exchanges code for tokens, stores in credential store
7. Temporary listener shuts down
8. Frontend polls `/api/accounts/auth/schwab/status` until connected

**Registered redirect URI:** `http://127.0.0.1:17723/callback/schwab`

For Plaid: use Plaid Link (JS widget) which runs entirely in the frontend and returns a public token -- no OAuth callback needed.

---

## 9. Security Controls

| Concern | Approach |
|---|---|
| **Credentials at rest** | OS keychain (primary) or Fernet-encrypted file |
| **Token refresh** | Auto-refresh before expiry; re-auth prompt if refresh token expires |
| **OAuth CSRF** | Random `state` parameter, verified on callback |
| **Callback isolation** | Only accept connections from `127.0.0.1` |
| **Rate limiting** | Per-adapter rate limiter (threading lock + delay), matching existing `_yf_rate_limited_download` pattern in `lib/cache.py` |
| **Order confirmation** | Mandatory confirmation dialog before any order submission |
| **Audit logging** | Append-only JSONL at `get_user_data_path("audit/")` for orders, auth events, position snapshots |
| **Memory cleanup** | Clear token strings on app quit (in `desktop_app.py` finally block) |
| **Token logging** | Never log full tokens -- truncated representations only |

---

## 10. Implementation Phases

| Phase | Scope | Dependencies |
|---|---|---|
| **1. Foundation** | `lib/credential_store.py`, `lib/brokers/base.py`, `lib/brokers/__init__.py` | `keyring`, `cryptography` |
| **2. Manual + UI** | `lib/brokers/manual.py`, `routes/accounts.py`, `templates/accounts.html`, `static/js/accounts.js` | Phase 1 |
| **3. Schwab** | `lib/brokers/schwab.py`, OAuth callback flow, `accounts_auth.js` | Phase 2, `schwab-py` |
| **4. Plaid** | `lib/brokers/plaid.py` (Fidelity + Vanguard read-only) | Phase 2, `plaid-python` |
| **5. SnapTrade** | `lib/brokers/snaptrade.py` (Robinhood) | Phase 2, `snaptrade-python-sdk` |
| **6. Intelligence** | `lib/portfolio_manager.py`, allocation charts, rebalancing engine | Phases 3-5 |

Phase 2 delivers immediate value with manual import before any API keys are needed.

---

## New Files

```
lib/
  credential_store.py          -- Secure credential management
  portfolio_manager.py         -- Aggregation, allocation, rebalancing
  brokers/
    __init__.py                -- Registry
    base.py                    -- Protocol + dataclasses
    schwab.py                  -- Schwab direct API
    plaid.py                   -- Plaid aggregator
    snaptrade.py               -- SnapTrade aggregator
    manual.py                  -- CSV/OFX import
routes/
  accounts.py                  -- New blueprint
templates/
  accounts.html                -- Portfolio management page
  partials/
    account_card.html
    allocation_chart.html
static/
  js/
    accounts.js
    accounts_auth.js
    accounts_charts.js
```

## Modified Files

- `routes/__init__.py` -- Register accounts blueprint
- `templates/partials/nav.html` (or toolbar equivalent) -- Add "Accounts" nav link
- `requirements.txt` -- Add `keyring`, `cryptography`, `schwab-py`, `plaid-python`, `snaptrade-python-sdk`
- `lib/settings.py` -- Rate limit constants for broker APIs
