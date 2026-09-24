/**
 * edit-modals.js - fills every "edit" modal from the row that was clicked.
 *
 * The pattern, used on five pages:
 *
 *   1. Each row's edit button carries the whole record as JSON in a
 *      `data-record` attribute, written by the template. For example, in
 *      workers.html:
 *
 *        <button class="edit-worker-btn"
 *                data-record='{"id": 3, "name": "Musonda Banda",
 *                              "status": "active", "hourly_rate": 18.0}'>
 *
 *   2. Clicking it copies each JSON field into the matching input in the
 *      shared modal, and points the modal's form at that record's update URL
 *      (here: /workers/3/update).
 *
 * Why do it this way rather than one modal per row: a table of 200 workers
 * would otherwise render 200 modals. One modal filled on demand keeps the page
 * small, and there is a single form to maintain per entity.
 *
 * The listener is delegated to `document` because DataTables removes rows from
 * the DOM when you page through the table - a listener bound directly to a
 * button on page 1 would be gone by page 2.
 *
 * To wire up a new entity, add an entry to `editConfigs`:
 *   idKey          which JSON field holds the primary key
 *   formId         the id of the modal's <form>
 *   actionBuilder  builds the POST URL from that key
 *   fields         JSON field name -> input element id
 *   textFields     JSON field name -> element whose textContent to set
 *                  (used for read-only labels such as "Worker ID: 0003")
 */
document.addEventListener('DOMContentLoaded', function () {
  var editConfigs = {
    // Workers page. Note there is no PIN here: a PIN can only be reset, never
    // read back, so it has its own modal and route.
    '.edit-worker-btn': {
      idKey: 'id',
      formId: 'editWorkerForm',
      actionBuilder: function (id) { return '/workers/' + id + '/update'; },
      fields: {
        name: 'editName',
        phone_number: 'editPhone',
        address: 'editAddress',
        emergency_contact: 'editEmergency',
        department: 'editDepartment',
        nrc_number: 'editNrc',
        status: 'editStatus',
        hourly_rate: 'editHourlyRate',
        payroll_period: 'editPayrollPeriod',
        enrollment_date: 'editEnrollmentDate'
      },
      textFields: {
        worker_id: 'editWorkerCode'
      }
    },

    // Users page. The password is absent for the same reason as the PIN.
    '.edit-user-btn': {
      idKey: 'id',
      formId: 'editUserForm',
      actionBuilder: function (id) { return '/users/' + id + '/update'; },
      fields: {
        name: 'editUserName',
        email: 'editUserEmail',
        phone: 'editUserPhone',
        role: 'editUserRole',
        linked_worker_id: 'editUserLinkedWorker'
      },
      textFields: {
        username: 'editUserUsername'
      }
    },

    // CCTV feeds. `rtsp_url` is the live stream source, e.g.
    // "rtsp://10.0.0.5:554/stream1" or "builtin://0" for this machine's camera.
    '.edit-feed-btn': {
      idKey: 'feed_id',
      formId: 'editFeedForm',
      actionBuilder: function (id) { return '/config/cctv-feeds/' + id + '/update'; },
      fields: {
        camera_name: 'editFeedName',
        camera_location: 'editFeedLocation',
        rtsp_url: 'editFeedSource',
        status: 'editFeedStatus'
      }
    },

    '.edit-device-btn': {
      idKey: 'device_id',
      formId: 'editDeviceForm',
      actionBuilder: function (id) { return '/config/biometric-devices/' + id + '/update'; },
      fields: {
        device_name: 'editDeviceName',
        device_serial: 'editDeviceSerial',
        device_type: 'editDeviceType',
        ip_address: 'editDeviceIp',
        usb_port: 'editDeviceUsb',
        status: 'editDeviceStatus',
        location: 'editDeviceLocation'
      }
    },

    // Payroll. Only hours, rate, status and dates are editable: gross pay,
    // NAPSA, NHIMA and net pay are recalculated server-side from those, so
    // there are deliberately no inputs for the amounts.
    '.edit-payroll-btn': {
      idKey: 'payroll_id',
      formId: 'editPayrollForm',
      actionBuilder: function (id) { return '/config/payroll/' + id + '/update'; },
      fields: {
        worker_id: 'editPayrollWorker',
        week_ending: 'editPayrollWeekEnding',
        payment_date: 'editPayrollPaymentDate',
        total_hours: 'editPayrollHours',
        overtime_hours: 'editPayrollOvertime',
        hourly_rate: 'editPayrollRate',
        paid_status: 'editPayrollStatus'
      }
    }
  };

  /** null and undefined must become an empty input, not the text "null". */
  function safeValue(value) {
    if (value === null || value === undefined) {
      return '';
    }
    return String(value);
  }

  function setInputValue(element, value) {
    if (!element) {
      return;
    }
    // <select> option values are lower case throughout ("active", "pending",
    // "supervisor"), so normalise before matching or the option silently fails
    // to select and the form submits the first option instead.
    if (element.tagName === 'SELECT') {
      element.value = safeValue(value).toLowerCase();
      return;
    }
    element.value = safeValue(value);
  }

  function setTextValue(element, value, fallback) {
    if (!element) {
      return;
    }
    element.textContent = value ? safeValue(value) : fallback;
  }

  function applyRecordToModal(record, config) {
    var form = document.getElementById(config.formId);
    if (!form) {
      return;
    }

    // Point the shared form at this particular record.
    var recordId = record[config.idKey];
    if (recordId) {
      form.action = config.actionBuilder(recordId);
    }

    Object.keys(config.fields || {}).forEach(function (recordKey) {
      setInputValue(document.getElementById(config.fields[recordKey]), record[recordKey]);
    });

    Object.keys(config.textFields || {}).forEach(function (recordKey) {
      setTextValue(document.getElementById(config.textFields[recordKey]), record[recordKey], '-');
    });
  }

  document.addEventListener('click', function (e) {
    Object.keys(editConfigs).forEach(function (selector) {
      var editBtn = e.target.closest(selector);
      if (!editBtn) {
        return;
      }

      var rawRecord = editBtn.getAttribute('data-record');
      if (!rawRecord) {
        return;
      }

      var record = {};
      try {
        record = JSON.parse(rawRecord);
      } catch (_) {
        // Malformed JSON should leave the modal blank rather than throwing and
        // stopping every other listener on the page.
        return;
      }

      applyRecordToModal(record, editConfigs[selector]);
    });
  });
});
