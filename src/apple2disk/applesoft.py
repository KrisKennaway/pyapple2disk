import anomaly
import container
import bitstring

TOKENS = {
    0x80: 'END',
    0x81: 'FOR',
    0x82: 'NEXT',
    0x83: 'DATA',
    0x84: 'INPUT',
    0x85: 'DEL',
    0x86: 'DIM',
    0x87: 'READ',
    0x88: 'GR',
    0x89: 'TEXT',
    0x8A: 'PR #',
    0x8B: 'IN #',
    0x8C: 'CALL',
    0x8D: 'PLOT',
    0x8E: 'HLIN',
    0x8F: 'VLIN',
    0x90: 'HGR2',
    0x91: 'HGR',
    0x92: 'HCOLOR=',
    0x93: 'HPLOT',
    0x94: 'DRAW',
    0x95: 'XDRAW',
    0x96: 'HTAB',
    0x97: 'HOME',
    0x98: 'ROT=',
    0x99: 'SCALE=',
    0x9A: 'SHLOAD',
    0x9B: 'TRACE',
    0x9C: 'NOTRACE',
    0x9D: 'NORMAL',
    0x9E: 'INVERSE',
    0x9F: 'FLASH',
    0xA0: 'COLOR=',
    0xA1: 'POP',
    0xA2: 'VTAB',
    0xA3: 'HIMEM:',
    0xA4: 'LOMEM:',
    0xA5: 'ONERR',
    0xA6: 'RESUME',
    0xA7: 'RECALL',
    0xA8: 'STORE',
    0xA9: 'SPEED=',
    0xAA: 'LET',
    0xAB: 'GOTO',
    0xAC: 'RUN',
    0xAD: 'IF',
    0xAE: 'RESTORE',
    0xAF: '&',
    0xB0: 'GOSUB',
    0xB1: 'RETURN',
    0xB2: 'REM',
    0xB3: 'STOP',
    0xB4: 'ON',
    0xB5: 'WAIT',
    0xB6: 'LOAD',
    0xB7: 'SAVE',
    0xB8: 'DEF FN',
    0xB9: 'POKE',
    0xBA: 'PRINT',
    0xBB: 'CONT',
    0xBC: 'LIST',
    0xBD: 'CLEAR',
    0xBE: 'GET',
    0xBF: 'NEW',
    0xC0: 'TAB',
    0xC1: 'TO',
    0xC2: 'FN',
    0xC3: 'SPC(',
    0xC4: 'THEN',
    0xC5: 'AT',
    0xC6: 'NOT',
    0xC7: 'STEP',
    0xC8: '+',
    0xC9: '-',
    0xCA: '*',
    0xCB: '/',
    0xCC: ';',
    0xCD: 'AND',
    0xCE: 'OR',
    0xCF: '>',
    0xD0: '=',
    0xD1: '<',
    0xD2: 'SGN',
    0xD3: 'INT',
    0xD4: 'ABS',
    0xD5: 'USR',
    0xD6: 'FRE',
    0xD7: 'SCRN (',
    0xD8: 'PDL',
    0xD9: 'POS',
    0xDA: 'SQR',
    0xDB: 'RND',
    0xDC: 'LOG',
    0xDD: 'EXP',
    0xDE: 'COS',
    0xDF: 'SIN',
    0xE0: 'TAN',
    0xE1: 'ATN',
    0xE2: 'PEEK',
    0xE3: 'LEN',
    0xE4: 'STR$',
    0xE5: 'VAL',
    0xE6: 'ASC',
    0xE7: 'CHR$',
    0xE8: 'LEFT$',
    0xE9: 'RIGHT$',
    0xEA: 'MID$'
}

class AppleSoft(container.Container):
    def __init__(self, filename, data):
        super(AppleSoft, self).__init__()

        self.filename = filename
        data = bitstring.ConstBitStream(data)

        # TODO: assert length is met
        self.length = data.read('uintle:16')

        self.lines = []
        self.program = {}
        last_line_number = -1
        last_memory = 0x801
        while data:
            next_memory, line_number = data.readlist('uintle:16, uintle:16')
            if not next_memory:
                break

            line = []
            bytes_read = 4
            while True:
                token = data.read('uint:8')
                bytes_read += 1
                if token == 0:
                    self.lines.append(line_number)
                    self.program[line_number] = ''.join(line)
                    break

                if token >= 0x80:
                    try:
                        line.append(' ' + TOKENS[token] + ' ')
                    except KeyError:
                        self.anomalies.append(anomaly.Anomaly(
                            self, anomaly.CORRUPTION, 'Line number %d contains unexpected token: %02X' % (
                                line_number, token)
                            )
                        )
                else:
                    line.append(chr(token))

            if last_memory + bytes_read != next_memory:
                self.anomalies.append(anomaly.Anomaly(
                    self, anomaly.UNUSUAL, "%x + %x == %x != %x (gap %d)" % (
                        last_memory, bytes_read, last_memory + bytes_read, next_memory,
                        next_memory - last_memory - bytes_read)
                    )
                )

            if line_number <= last_line_number:
                self.anomalies.append(anomaly.Anomaly(
                    self, anomaly.UNUSUAL, "%d <= %d: %s" % (
                        line_number, last_line_number, ''.join(line))
                    )
                )

            last_line_number = line_number
            last_memory = next_memory

    def List(self):
        return '\n'.join('%s %s' % (num, self.program[num]) for num in self.lines)

    def __str__(self):
        return 'AppleSoft(%s)' % self.filename

