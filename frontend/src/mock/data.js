export const MOCK_SUBJECTS = [
  {
    id: 1,
    subjectCode: 'DEMO-001',
    alias: '张**',
    gender: 'M',
    age: 68,
    apoe: 'E3/E4',
    diagnosis: 'AD',
    riskScore: 0.82,
    qualityStatus: 'PASS',
    status: 'ACTIVE',
    dataVersion: 'demo-v1.0',
    createdAt: '2026-09-15 10:22:03'
  },
  {
    id: 2,
    subjectCode: 'DEMO-002',
    alias: '李**',
    gender: 'F',
    age: 72,
    apoe: 'E3/E3',
    diagnosis: 'MCI',
    riskScore: 0.45,
    qualityStatus: 'PASS',
    status: 'ACTIVE',
    dataVersion: 'demo-v1.0',
    createdAt: '2026-09-16 11:05:47'
  },
  {
    id: 3,
    subjectCode: 'DEMO-003',
    alias: '王**',
    gender: 'M',
    age: 65,
    apoe: 'E4/E4',
    diagnosis: 'AD',
    riskScore: null,
    qualityStatus: 'BLOCKED',
    status: 'ACTIVE',
    dataVersion: 'demo-v1.0',
    createdAt: '2026-09-18 09:17:11'
  },
  {
    id: 4,
    subjectCode: 'DEMO-004',
    alias: '赵**',
    gender: 'F',
    age: 58,
    apoe: 'E3/E4',
    diagnosis: 'Normal',
    riskScore: 0.21,
    qualityStatus: 'PASS',
    status: 'ACTIVE',
    dataVersion: 'demo-v1.1',
    createdAt: '2026-09-20 14:30:22'
  },
  {
    id: 5,
    subjectCode: 'DEMO-005',
    alias: '刘**',
    gender: 'M',
    age: 74,
    apoe: 'E2/E3',
    diagnosis: 'MCI',
    riskScore: 0.58,
    qualityStatus: 'WARN',
    status: 'ACTIVE',
    dataVersion: 'demo-v1.1',
    createdAt: '2026-09-22 16:44:58'
  },
  {
    id: 6,
    subjectCode: 'DEMO-006',
    alias: '陈**',
    gender: 'F',
    age: 61,
    apoe: 'E3/E3',
    diagnosis: 'AD',
    riskScore: 0.73,
    qualityStatus: 'PASS',
    status: 'ARCHIVED',
    dataVersion: 'demo-v1.0',
    createdAt: '2026-09-25 08:12:34'
  }
]

export const MOCK_VISITS = {
  1: [
    { id: 101, visitCode: 'V001-01', visitDate: '2026-09-20 09:30:00', mmse: 22, moca: 18, cdrSb: 3.0 },
    { id: 102, visitCode: 'V001-02', visitDate: '2026-10-05 10:15:00', mmse: 20, moca: 16, cdrSb: 3.5 }
  ],
  2: [
    { id: 201, visitCode: 'V002-01', visitDate: '2026-09-22 14:00:00', mmse: 26, moca: 23, cdrSb: 1.0 }
  ],
  3: [],
  4: [
    { id: 401, visitCode: 'V004-01', visitDate: '2026-09-25 11:20:00', mmse: 29, moca: 27, cdrSb: 0.0 },
    { id: 402, visitCode: 'V004-02', visitDate: '2026-10-10 11:00:00', mmse: 28, moca: 26, cdrSb: 0.0 }
  ],
  5: [
    { id: 501, visitCode: 'V005-01', visitDate: '2026-09-28 09:00:00', mmse: 25, moca: 21, cdrSb: 1.5 }
  ],
  6: [
    { id: 601, visitCode: 'V006-01', visitDate: '2026-09-30 15:30:00', mmse: 19, moca: 14, cdrSb: 4.0 }
  ]
}

export function mockDelay(ms = 300) {
  return new Promise(resolve => setTimeout(resolve, ms))
}