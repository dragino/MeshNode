#include "configuration.h"

#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)

#include "DraginoBluetooth.h"

#include "DraginoDefaultConfig.h"
#include "SerialConsole.h"
#include "PrivateConfig.h"
#include "mesh/NodeDB.h"
#include <string.h>

// Serial port shared with SerialConsole (PA2/PA3, USART2)
#define BT_SERIAL Serial

// AT response read buffer size
#define AT_RX_BUF 128

static constexpr uint32_t BT_TARGET_BAUD = 115200;

class NullPrint : public Print {
public:
    size_t write(uint8_t) override { return 1; }
};
static NullPrint nullPrint;

namespace dragino {

DraginoBluetooth *draginoBluetooth = nullptr;

// ---------------------------------------------------------------------------
// AT sequences
// ---------------------------------------------------------------------------

// Hibernate sequence (module must be in ADVERTISING state, not connected)
static const AtCmd hibernateSeq[] = {
    {"AT+PWRM2", "OK", 500},
};

// ---------------------------------------------------------------------------
// Constructor
// ---------------------------------------------------------------------------

DraginoBluetooth::DraginoBluetooth() : OSThread("DraginoBluetooth", 100)
{
    draginoBluetooth = this;

    pinMode(DRAGINO_BT_LINK_PIN, INPUT);
    pinMode(DRAGINO_BT_WORK_PIN, INPUT);
    pinMode(DRAGINO_BT_KEY_PIN,  OUTPUT);
    pinMode(DRAGINO_BT_RST_PIN,  OUTPUT);

    digitalWrite(DRAGINO_BT_KEY_PIN, HIGH);
    digitalWrite(DRAGINO_BT_RST_PIN, HIGH);

    delay(100);

    bool workAlwaysLow = true;
    uint32_t checkStart = millis();
    while (millis() - checkStart < 500) {
        if (digitalRead(DRAGINO_BT_WORK_PIN) == HIGH) {
            workAlwaysLow = false;
            break;
        }
        delay(10);
    }

    if (workAlwaysLow) {
        LOG_INFO("BT WORK_PIN LOW >500ms at boot, hibernate mode");
        enterState(HIBERNATING);
    } else {
        enterState(BOOTING);
    }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

void DraginoBluetooth::toggle()
{
    if (state_ == HIBERNATING) {
        if (digitalRead(DRAGINO_BT_WORK_PIN) == HIGH) {
            LOG_WARN("BT toggle: WORK_PIN already HIGH, skip RST pulse");
            enterState(BOOTING);
            return;
        }
        doWakeup();
    }
}

bool DraginoBluetooth::isConnected() const
{
    return digitalRead(DRAGINO_BT_LINK_PIN) == HIGH;
}

// ---------------------------------------------------------------------------
// OSThread::runOnce
// ---------------------------------------------------------------------------

int32_t DraginoBluetooth::runOnce()
{
    switch (state_) {

    case HIBERNATING:
        // Nothing to do; waiting for toggle()
        return 500;

    case BOOTING: {
        bool workHigh = (digitalRead(DRAGINO_BT_WORK_PIN) == HIGH);
        if (workHigh) {
            enterState(INITIALIZING);
        } else if (millis() - stateEnteredMs_ >= 500) {
            LOG_INFO("BT WORK_PIN LOW >500ms, module not active");
            enterState(HIBERNATING);
        }
        return 100;
    }

    case INITIALIZING:
        if (runInitSequence()) {
            initRetryCount_ = 0;
            if (wakeForUse_) {
                wakeForUse_ = false;
                enterState(ADVERTISING);
            } else {
                doHibernate();
            }
        } else {
            initRetryCount_++;
            if (initRetryCount_ >= 2) {
                LOG_ERROR("BT init failed after %d attempts, giving up", initRetryCount_);
                initRetryCount_ = 0;
                enterState(HIBERNATING);
            } else {
                LOG_WARN("BT init attempt %d/2 failed", initRetryCount_);
                enterState(BOOTING);
            }
        }
        return 0;

    case ADVERTISING:
        if (isConnected()) {
            enterState(CONNECTED);
        }
        return 200;

    case CONNECTED:
        if (!isConnected()) {
            enterState(ADVERTISING);
        }
        return 200;
    }

    return 100;
}

// ---------------------------------------------------------------------------
// State machine
// ---------------------------------------------------------------------------

void DraginoBluetooth::enterState(State s)
{
    state_ = s;
    stateEnteredMs_ = millis();
    if (s != INITIALIZING) {
        LOG_DEBUG("BT state -> %d", (int)s);
    }
}

void DraginoBluetooth::doWakeup()
{
    LOG_INFO("BT wakeup via RST pulse");
    wakeForUse_ = true;
    pulseRst(300);
    enterState(BOOTING);
}

void DraginoBluetooth::doHibernate()
{
    if (isConnected()) {
        LOG_INFO("BT disconnecting before hibernate");
        pulseKey(200);
        uint32_t deadline = millis() + 2000;
        while (isConnected() && millis() < deadline) {
            delay(50);
        }
    }

    if (runHibernateSequence()) {
        enterState(HIBERNATING);
        LOG_INFO("BT entered hibernate");
    } else {
        LOG_WARN("BT hibernate AT failed, forcing RST");
        pulseRst(300);
        enterState(BOOTING);
    }
}

void DraginoBluetooth::shutdown()
{
    if (state_ == HIBERNATING) {
        return;
    }
    doHibernate();
}

void DraginoBluetooth::prepareForSleep()
{
    if (state_ == HIBERNATING && digitalRead(DRAGINO_BT_WORK_PIN) == LOW) {
        setSleepPins();
        return;
    }

    if (isConnected()) {
        LOG_INFO("BT disconnecting before sleep");
        pulseKey(200);
        uint32_t deadline = millis() + 2000;
        while (isConnected() && millis() < deadline) {
            delay(50);
        }
    }

    bool hibernated = runHibernateSequence();
    delay(300);
    bool workLow = digitalRead(DRAGINO_BT_WORK_PIN) == LOW;

    if (hibernated || workLow) {
        enterState(HIBERNATING);
        LOG_INFO("BT prepared for sleep (at=%d work=%d)", hibernated ? 1 : 0, workLow ? 0 : 1);
    } else {
        LOG_WARN("BT sleep AT failed and WORK_PIN still HIGH, forcing MCU-side sleep pins");
        enterState(HIBERNATING);
    }

    setSleepPins();
}

bool DraginoBluetooth::canSleep() const
{
    return (state_ == HIBERNATING || state_ == ADVERTISING);
}

void DraginoBluetooth::resumeAfterStop(bool wakeForUse)
{
    pinMode(DRAGINO_BT_LINK_PIN, INPUT);
    pinMode(DRAGINO_BT_WORK_PIN, INPUT);
    pinMode(DRAGINO_BT_KEY_PIN, OUTPUT);
    pinMode(DRAGINO_BT_RST_PIN, OUTPUT);

    digitalWrite(DRAGINO_BT_KEY_PIN, HIGH);
    digitalWrite(DRAGINO_BT_RST_PIN, HIGH);

    initRetryCount_ = 0;
    wakeForUse_ = false;

    if (wakeForUse) {
        doWakeup();
    } else if (digitalRead(DRAGINO_BT_WORK_PIN) == HIGH) {
        enterState(BOOTING);
    } else {
        enterState(HIBERNATING);
    }

    setIntervalFromNow(0);
}

// ---------------------------------------------------------------------------
// GPIO helpers
// ---------------------------------------------------------------------------

void DraginoBluetooth::pulseRst(uint32_t ms)
{
    digitalWrite(DRAGINO_BT_RST_PIN, LOW);
    delay(ms);
    digitalWrite(DRAGINO_BT_RST_PIN, HIGH);
    delay(200); // allow module to boot
}

void DraginoBluetooth::pulseKey(uint32_t ms)
{
    digitalWrite(DRAGINO_BT_KEY_PIN, LOW);
    delay(ms);
    digitalWrite(DRAGINO_BT_KEY_PIN, HIGH);
}

void DraginoBluetooth::setSleepPins()
{
    BT_SERIAL.flush();
    BT_SERIAL.end();
    digitalWrite(DRAGINO_BT_KEY_PIN, HIGH);
    digitalWrite(DRAGINO_BT_RST_PIN, HIGH);
    pinMode(DRAGINO_BT_LINK_PIN, INPUT);
    pinMode(DRAGINO_BT_WORK_PIN, INPUT);
    pinMode(DRAGINO_BT_KEY_PIN, INPUT_ANALOG);
    pinMode(DRAGINO_BT_RST_PIN, INPUT_ANALOG);
}

// ---------------------------------------------------------------------------
// AT layer
// ---------------------------------------------------------------------------

void DraginoBluetooth::beginAtWindow(uint32_t baud)
{
    if (console) {
        console->suspend();
        console->setDestination(&nullPrint);
    }

    BT_SERIAL.flush();
    while (BT_SERIAL.available()) {
        BT_SERIAL.read();
    }

    BT_SERIAL.end();
    BT_SERIAL.begin(baud);
    BT_SERIAL.setTimeout(150);

    delay(50);

    while (BT_SERIAL.available()) {
        BT_SERIAL.read();
    }
}

void DraginoBluetooth::endAtWindow()
{
    BT_SERIAL.flush();

    while (BT_SERIAL.available()) {
        BT_SERIAL.read();
    }

    switchBaud(BT_TARGET_BAUD);

    if (console) {
        console->setDestination(&BT_SERIAL);
        console->resume();
        console->delayNextRun(0);
    }
}

void DraginoBluetooth::switchBaud(uint32_t baud)
{
    BT_SERIAL.end();
    BT_SERIAL.begin(baud);
    BT_SERIAL.setTimeout(80);
}

void DraginoBluetooth::drain()
{
    while (BT_SERIAL.available()) {
        BT_SERIAL.read();
    }
}

bool DraginoBluetooth::sendAt(const char *cmd, const char *expect, uint32_t timeoutMs)
{
    BT_SERIAL.flush();

    while (BT_SERIAL.available()) {
        BT_SERIAL.read();
    }

    BT_SERIAL.print(cmd);
    BT_SERIAL.print("\r\n");
    BT_SERIAL.flush();

    bool found = false;
    uint32_t deadline = millis() + timeoutMs;
    char buf[AT_RX_BUF];

    while (millis() < deadline) {
        int len = BT_SERIAL.readBytesUntil('\n', buf, sizeof(buf) - 1);
        if (len <= 0) {
            continue;
        }

        buf[len] = '\0';

        while (len > 0 && (buf[len - 1] == '\r' || buf[len - 1] == '\n')) {
            buf[--len] = '\0';
        }

        if (len == 0) {
            continue;
        }

        if (strstr(buf, expect) != nullptr) {
            found = true;
            break;
        }

        if (strstr(buf, "ERROR=") != nullptr) {
            break;
        }
    }

    return found;
}

bool DraginoBluetooth::sendAtCollect(const char *cmd, char *outBuf, size_t outBufSize, uint32_t timeoutMs)
{
    if (!outBuf || outBufSize == 0) {
        return false;
    }

    outBuf[0] = '\0';

    BT_SERIAL.flush();
    while (BT_SERIAL.available()) {
        BT_SERIAL.read();
    }

    BT_SERIAL.print(cmd);
    BT_SERIAL.print("\r\n");
    BT_SERIAL.flush();

    uint32_t deadline = millis() + timeoutMs;
    size_t used = 0;
    char line[AT_RX_BUF];

    while (millis() < deadline) {
        int len = BT_SERIAL.readBytesUntil('\n', line, sizeof(line) - 1);
        if (len <= 0) {
            continue;
        }

        line[len] = '\0';

        while (len > 0 && (line[len - 1] == '\r' || line[len - 1] == '\n')) {
            line[--len] = '\0';
        }

        if (len == 0) {
            continue;
        }

        if (used + len + 2 < outBufSize) {
            memcpy(outBuf + used, line, len);
            used += len;
            outBuf[used++] = '\n';
            outBuf[used] = '\0';
        }

        if (strstr(line, "OK") != nullptr || strstr(line, "ERROR=") != nullptr || strstr(line, "Power On") != nullptr) {
            break;
        }
    }

    return used > 0;
}

bool DraginoBluetooth::queryBtName(char *nameBuf, size_t nameBufSize)
{
    if (!nameBuf || nameBufSize == 0) {
        return false;
    }

    nameBuf[0] = '\0';

    char resp[256] = {0};
    if (!sendAtCollect("AT+NAME", resp, sizeof(resp), 600)) {
        return false;
    }

    const char *p = strstr(resp, "+NAME=");
    if (!p) {
        return false;
    }

    p += strlen("+NAME=");

    size_t i = 0;
    while (*p && *p != '\r' && *p != '\n' && i + 1 < nameBufSize) {
        nameBuf[i++] = *p++;
    }
    nameBuf[i] = '\0';

    return i > 0;
}

bool DraginoBluetooth::runAtSequence(const AtCmd *cmds, size_t count)
{
    for (size_t i = 0; i < count; i++) {
        if (!sendAt(cmds[i].cmd, cmds[i].expect, cmds[i].timeoutMs)) {
            return false;
        }
    }
    return true;
}

// ---------------------------------------------------------------------------
// AT sequences
// ---------------------------------------------------------------------------

bool DraginoBluetooth::runInitSequence()
{
    const char *devName = owner.long_name;
    if (devName == nullptr || devName[0] == '\0') {
        devName = DRAGINO_DEFAULT_DEVICE_NAME;
    }

    bool configuredFrom9600 = false;
    bool needRename = false;
    char currentName[32] = {0};
    int atCount = 0;

    beginAtWindow(BT_TARGET_BAUD);

    // ----------------------------------------------------------------
    // Phase 1: try 115200 first (most likely after previous config)
    // ----------------------------------------------------------------
    bool alive = false;
    for (int retry = 0; retry < 3; retry++) {
        atCount++;
        if (sendAt("AT", "OK", 500)) {
            alive = true;
            break;
        }
    }

    if (!alive) {
        // ------------------------------------------------------------
        // Phase 2: fall back to 9600 (factory default)
        // Still inside the same AT window — log output remains suppressed
        // ------------------------------------------------------------
        switchBaud(9600);
        delay(500);
        drain();

        for (int retry = 0; retry < 3; retry++) {
            atCount++;
            if (sendAt("AT", "OK", 500)) {
                alive = true;
                break;
            }
        }

        if (!alive) {
            endAtWindow();
            LOG_ERROR("BT init failed after %d AT cmds", atCount);
            return false;
        }

        // Configure baud to 115200 and enable notifications
        atCount++;
        if (!sendAt("AT+BAUD7", "OK", 500)) {
            switchBaud(BT_TARGET_BAUD);
            endAtWindow();
            LOG_ERROR("BT AT+BAUD7 failed (%d cmds)", atCount);
            return false;
        }

        atCount++;
        if (!sendAt("AT+NOTI1", "OK", 500)) {
            switchBaud(BT_TARGET_BAUD);
            endAtWindow();
            LOG_ERROR("BT AT+NOTI1 failed (%d cmds)", atCount);
            return false;
        }

        // Reset to apply baud change
        atCount++;
        BT_SERIAL.print("AT+RESET\r\n");
        BT_SERIAL.flush();
        delay(1500);

        switchBaud(BT_TARGET_BAUD);
        delay(300);
        drain();

        atCount++;
        if (!sendAt("AT", "OK", 800)) {
            endAtWindow();
            LOG_ERROR("BT post-reset AT failed (%d cmds)", atCount);
            return false;
        }

        configuredFrom9600 = true;
    }

    // ----------------------------------------------------------------
    // Phase 3: at 115200 — check / set device name
    // ----------------------------------------------------------------
    atCount++;
    if (!queryBtName(currentName, sizeof(currentName))) {
        endAtWindow();
        LOG_ERROR("BT AT+NAME query failed (%d cmds)", atCount);
        return false;
    }

    if (strcmp(currentName, devName) != 0) {
        needRename = true;

        char nameCmd[48];
        snprintf(nameCmd, sizeof(nameCmd), "AT+NAME%s", devName);

        atCount++;
        if (!sendAt(nameCmd, "OK", 600)) {
            endAtWindow();
            LOG_ERROR("BT AT+NAME failed (%d cmds)", atCount);
            return false;
        }

        // Name change may require reset
        atCount++;
        BT_SERIAL.print("AT+RESET\r\n");
        BT_SERIAL.flush();
        delay(1500);

        switchBaud(BT_TARGET_BAUD);
        delay(300);
        drain();

        atCount++;
        if (!sendAt("AT", "OK", 800)) {
            endAtWindow();
            LOG_ERROR("BT post-rename AT failed (%d cmds)", atCount);
            return false;
        }
    }

    endAtWindow();

    LOG_INFO("BT init done: %d AT cmds, 9600=%s, name=%s",
             atCount,
             configuredFrom9600 ? "yes" : "no",
             needRename ? devName : currentName);

    return true;
}

bool DraginoBluetooth::runHibernateSequence()
{
    beginAtWindow(BT_TARGET_BAUD);
    bool ok = runAtSequence(hibernateSeq, sizeof(hibernateSeq) / sizeof(hibernateSeq[0]));
    endAtWindow();
    return ok;
}

} // namespace dragino

#endif // defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
