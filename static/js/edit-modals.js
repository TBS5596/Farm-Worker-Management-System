document.addEventListener('DOMContentLoaded', function () {
  const editConfigs = {
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
        enrollment_date: 'editEnrollmentDate'
      },
      textFields: {
        worker_id: 'editWorkerCode'
      }
    },
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
    '.edit-payroll-btn': {
      idKey: 'payroll_id',
      formId: 'editPayrollForm',
      actionBuilder: function (id) { return '/config/payroll/' + id + '/update'; },
      fields: {
        worker_id: 'editPayrollWorker',
        week_ending: 'editPayrollWeekEnding',
        payment_date: 'editPayrollPaymentDate',
        total_hours: 'editPayrollHours',
        hourly_rate: 'editPayrollRate',
        gross_pay: 'editPayrollGross',
        paid_status: 'editPayrollStatus',
        napsa_deduction: 'editPayrollNapsa',
        nhima_deduction: 'editPayrollNhima',
        net_pay: 'editPayrollNet'
      }
    }
  };

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
    const form = document.getElementById(config.formId);
    if (!form) {
      return;
    }

    const recordId = record[config.idKey];
    if (recordId) {
      form.action = config.actionBuilder(recordId);
    }

    Object.keys(config.fields || {}).forEach(function (recordKey) {
      const targetId = config.fields[recordKey];
      setInputValue(document.getElementById(targetId), record[recordKey]);
    });

    Object.keys(config.textFields || {}).forEach(function (recordKey) {
      const targetId = config.textFields[recordKey];
      setTextValue(document.getElementById(targetId), record[recordKey], '-');
    });
  }

  document.addEventListener('click', function (e) {
    Object.keys(editConfigs).forEach(function (selector) {
      const editBtn = e.target.closest(selector);
      if (!editBtn) {
        return;
      }

      const rawRecord = editBtn.getAttribute('data-record');
      if (!rawRecord) {
        return;
      }

      let record = {};
      try {
        record = JSON.parse(rawRecord);
      } catch (_) {
        return;
      }

      applyRecordToModal(record, editConfigs[selector]);
    });
  });
});
