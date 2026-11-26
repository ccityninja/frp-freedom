'use strict';

const $ = id => document.getElementById(id);
const support = {
  android: ['https://support.google.com/android/', 'Official Android support'],
  iphone: ['https://support.apple.com/iphone', 'Official iPhone support'],
  androidAccount: ['https://support.google.com/accounts/answer/7682439', 'Google Account recovery help'],
  iphoneAccount: ['https://support.apple.com/en-us/108934', 'Apple Activation Lock support'],
};

const shared = {
  power: [
    'If the phone is swollen, unusually hot, or shows liquid damage, disconnect power and stop charging it.',
    'Try a known-good wall adapter, cable, and outlet. Leave it charging for 30 minutes if it stays cool.',
    'Look for a charge icon, vibration, or ringtone. A phone that rings with a blank screen may have a display problem.',
  ],
  screen: [
    'Disconnect accessories, remove the case or screen protector, and check whether touch improves on a clean, dry screen.',
    'If the screen is black but the phone rings or vibrates, prioritize display diagnosis over a reset.',
    'If touch works intermittently, back up your data before further testing.',
  ],
  audio: [
    'Turn Bluetooth off and remove the case. Check whether audio is routing to another device.',
    'Test a local voice recording and play known-good media. Try each with and without headphones to narrow down the fault.',
    'Check the affected app’s microphone permission. If the problem happens across apps, use the manufacturer’s service guidance.',
  ],
};
const guides = {
  android: {
    connection: ['Try a known data cable and a different USB port directly on the computer.', 'Unlock the phone. For copying files, choose File transfer in the phone’s USB notification.', 'For Android health checks only, enable USB debugging if you have access to Settings and approve the prompt for this computer.'],
    boot: ['Disconnect accessories and check for a stuck power button.', 'Look up the exact model’s supported restart or Safe Mode steps. If it boots, back up before changing anything.', 'If it won’t boot, check the manufacturer’s official recovery options. Don’t choose a factory reset if you need the data.'],
    storage: ['Open Settings → Storage to see what’s taking up space.', 'Copy important files and verify the copies open before deleting originals. Clear cache before considering app data.', 'If ADB is authorized, use Read Android health to check available space on /data.'],
    backup: ['Check the current backup status in Android Settings; availability varies by phone.', 'Copy important photos and files using your usual backup or USB File transfer. Verify a few files open from the copy.', 'Check authenticator, chat, and other app-specific backups separately. A system backup might not include them.'],
    account: ['Use Google’s recovery page to regain access to the Google Account previously used on the phone.', 'For a used phone, ask the seller to resolve the account lock with you or return it.', 'If account recovery fails, contact the manufacturer with proof of purchase. Don’t share passwords or verification codes with a repair tool.'],
  },
  iphone: {
    connection: ['Try a known data cable and a different port, without a hub.', 'Unlock the phone and approve Trust This Computer only for a computer you recognize.', 'Check Finder on Mac or Apple Devices on Windows. The ADB health check on this page doesn’t apply to iPhone.'],
    boot: ['Check for stuck buttons and follow Apple’s force-restart steps for your exact model.', 'If Finder or Apple Devices offers Update or Restore, Apple’s Update option attempts to reinstall iOS without erasing data.', 'Restore erases the phone. If you need the data and don’t have a verified backup, stop before choosing Restore.'],
    storage: ['Open Settings → General → iPhone Storage.', 'Review large downloads and unused apps. Offload App keeps its documents and data; Delete App can remove them.', 'Verify photos and other important data are backed up before deleting originals.'],
    backup: ['Use iCloud Backup or make a computer backup in Finder or Apple Devices.', 'If you choose an encrypted computer backup, keep its password somewhere safe; you’ll need it to restore.', 'Verify the latest backup completed before starting any repair that could erase the phone.'],
    account: ['Use the Apple Account associated with the device, or recover that account through Apple.', 'If bought used, ask the previous owner to remove the device from their account or arrange a return.', 'Apple provides an Activation Lock support request for eligible devices with proof of purchase.'],
  },
};

function renderGuide() {
  const platform = $('platform').value;
  const symptom = $('action').value;
  const items = guides[platform][symptom] ?? shared[symptom];
  $('steps').replaceChildren(...items.map(text => Object.assign(document.createElement('li'), {textContent: text})));
  const [href, label] = support[symptom === 'account' ? `${platform}Account` : platform];
  $('support').href = href;
  $('support').textContent = label;
}

const probeStatuses = {missing:'tool not installed', timeout:'timed out', error:'probe failed'};
const adbStates = {authorized:'authorized', unauthorized:'awaiting approval', offline:'offline', permission_denied:'host permission denied', other:'other state'};
const healthStatuses = {
  no_device:'Connect an Android phone with a data cable, enable USB debugging, and approve this computer on the phone.',
  unauthorized:'Unlock Android and approve the USB debugging prompt on the phone, then try again.',
  offline:'ADB sees the phone but it is offline. Reconnect it and try again.',
  recovery:'The phone is in recovery. If you can boot Android normally, do that before reading health.',
  sideload:'The phone is in ADB sideload mode. Health readings are only available in normal Android.',
  rescue:'The phone is in rescue mode. Health readings are only available in normal Android.',
  bootloader:'The phone is in bootloader mode. Health readings are only available in normal Android.',
  multiple_devices:'Disconnect the other phones, wireless ADB devices, or emulators, then try again.',
  unavailable:'The device transport can’t be read. Check ADB status, driver permissions, and platform-tools version.',
  no_readings:'ADB found the phone, but none of the health readings came back. Run the USB connection check, then retry.',
  busy:'Another diagnostic is running. Try again when it finishes.',
};
const POLL_MS = 3000;
let pollTimer, pendingConnection, previousUsbCount, usbChange;
let healthReady = false;
let healthRunning = false;

async function readProbe(path) {
  const response = await fetch(path, {cache:'no-store'});
  if (response.status === 503) return {status:'busy'};
  if (!response.ok) throw new Error('request failed');
  return response.json();
}

function connectMessage(data) {
  const usb = data.usb.status === 'ok'
    ? `USB: ${data.usb.non_root_hub_count} peripherals (including built-ins).`
    : `USB: ${probeStatuses[data.usb.status] ?? 'unavailable'}.`;
  const states = Object.entries(data.adb.states).map(([state,count]) => `${count} ${adbStates[state] ?? 'other'}`);
  const adb = data.adb.status === 'ok'
    ? (states.length ? `ADB: ${states.join(', ')}.` : 'ADB: no devices listed.')
    : `ADB: ${probeStatuses[data.adb.status] ?? 'unavailable'}.`;
  return `${usb} ${adb}`;
}

function updateHealthAvailability(ready, message) {
  healthReady = ready;
  $('health').disabled = healthRunning || !ready;
  $('health-availability').textContent = message;
  if (!ready && !$('metrics').hidden) {
    $('metrics').hidden = true;
    $('health-status').textContent = 'Previous readings cleared. Read health again when the phone is ready.';
  }
}

function connectionBadge(label, hint, tone = '') {
  const badge = $('connection-badge');
  if (badge.textContent !== label) badge.textContent = label;
  badge.dataset.tone = tone;
  $('connection-hint').textContent = hint;
}

function renderConnection(data) {
  if (data.status === 'busy') {
    $('connection-status').textContent = 'Another diagnostic is running. Live updates will retry automatically.';
    return;
  }
  const count = data.usb.non_root_hub_count;
  if (data.usb.status === 'ok') {
    if (previousUsbCount !== undefined && count !== previousUsbCount) usbChange = count - previousUsbCount;
    previousUsbCount = count;
  }

  const status = data.health_status;
  const ready = status === 'ready';
  const hint = ready ? 'Choose Read Android health to see battery, temperature, storage, and Android version.'
    : healthStatuses[status] ?? `ADB: ${probeStatuses[status] ?? 'unavailable'}.`;
  updateHealthAvailability(ready, hint);
  if (ready) {
    connectionBadge(data.adb.usb_transports ? 'Android connected via USB' : 'ADB ready · USB not confirmed', hint, 'ready');
  } else if (status === 'unauthorized') {
    connectionBadge('Approval needed on Android', hint, 'attention');
  } else if (data.adb.status === 'ok' && Object.keys(data.adb.states).length) {
    connectionBadge('ADB detected · health unavailable', hint, 'attention');
  } else if (data.usb.status === 'ok' && usbChange) {
    connectionBadge(usbChange > 0 ? 'USB device added' : 'USB device removed',
      'The USB device count changed. Without authorized debugging, this check can’t confirm which device changed.');
  } else if (data.adb.status !== 'ok' && data.usb.status !== 'ok') {
    connectionBadge('Detection unavailable', 'Check that adb and lsusb are installed on this computer.', 'attention');
  } else {
    connectionBadge('No phone confirmed', 'Watching for a USB change. If your phone was already plugged in and debugging is off, unplug it and reconnect.');
  }
  $('connection-status').textContent = connectMessage(data);
}

function refreshConnection() {
  if (pendingConnection || healthRunning) return pendingConnection;
  clearTimeout(pollTimer);
  pendingConnection = readProbe('/api/connection').then(renderConnection).catch(() => {
    const message = 'Check that Phone Repair Studio is running. The page will retry automatically.';
    connectionBadge('Live status unavailable', message, 'attention');
    $('connection-status').textContent = 'Couldn’t refresh the USB and ADB report.';
    updateHealthAvailability(false, message);
  }).finally(() => {
    pendingConnection = undefined;
    if (!document.hidden && !healthRunning) pollTimer = setTimeout(refreshConnection, POLL_MS);
  });
  return pendingConnection;
}

function renderHealth(data) {
  if (!['ok','partial'].includes(data.status)) {
    return healthStatuses[data.status] ?? `ADB: ${probeStatuses[data.status] ?? 'unavailable'}.`;
  }
  const gib = kib => `${(kib / 1048576).toFixed(2)} GiB`;
  const metrics = [
    ['Android', data.android_version],
    ['Charge level', data.battery?.percent == null ? null : `${data.battery.percent}%`],
    ['Charging state', data.battery?.state],
    ['Battery temperature', data.battery?.temp_c == null ? null : `${data.battery.temp_c.toFixed(1)} °C`],
    ['Data partition free', data.storage ? `${gib(data.storage.available_kib)} of ${gib(data.storage.total_kib)}` : null],
  ];
  const list = $('metrics');
  list.replaceChildren(...metrics.flatMap(([label,value]) => [
    Object.assign(document.createElement('dt'), {textContent: label}),
    Object.assign(document.createElement('dd'), {textContent: value ?? 'Unavailable'}),
  ]));
  list.hidden = false;
  return data.status === 'partial' ? 'Some readings weren’t available.' : 'Read-only snapshot complete.';
}

function renderAction() {
  const showHealth = $('action').value === 'health';
  $('health-panel').hidden = !showHealth;
  $('guide-panel').hidden = showHealth;
  if (!showHealth) renderGuide();
}

async function runHealth() {
  if (!healthReady || healthRunning) return;
  healthRunning = true;
  clearTimeout(pollTimer);
  $('health').disabled = true;
  $('connection').disabled = true;
  const status = $('health-status');
  status.textContent = 'Reading Android health…';
  $('metrics').hidden = true;
  try {
    await pendingConnection;
    if (!healthReady) {
      status.textContent = 'The connection changed. Check the live status and try again.';
      return;
    }
    status.textContent = renderHealth(await readProbe('/api/health'));
  } catch {
    status.textContent = 'Couldn’t get the report. Check that Phone Repair Studio is running and try again.';
  } finally {
    healthRunning = false;
    $('health').disabled = !healthReady;
    $('connection').disabled = false;
    if (!document.hidden) refreshConnection();
  }
}

$('platform').addEventListener('change', renderAction);
$('action').addEventListener('change', renderAction);
$('connection').addEventListener('click', refreshConnection);
$('health').addEventListener('click', runHealth);
document.addEventListener('visibilitychange', () => {
  if (document.hidden) clearTimeout(pollTimer);
  else refreshConnection();
});
renderAction();
if (!document.hidden) refreshConnection();
