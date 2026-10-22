"""Pure-Python LZO1X decompressor (port of minilzo's lzo1x_decompress).

decompress(src, pos, out_len) -> (bytes, new_pos)

Decodes one LZO1X stream starting at src[pos] until its end marker and
returns the decompressed bytes plus the offset just past the end marker.
"""

M2_MAX_OFFSET = 0x0800


def decompress(src, ip, out_len):
    out = bytearray(out_len)
    op = 0
    mv = src  # bytes-like, indexable

    def copy_match(op, m_pos, n):
        # overlapping-safe backreference copy
        if m_pos + n <= op:
            out[op:op + n] = out[m_pos:m_pos + n]
        else:
            for _ in range(n):
                out[op] = out[m_pos]
                op += 1
                m_pos += 1
            return op
        return op + n

    t = mv[ip]
    state = 0  # 0 = main loop, 1 = first_literal_run, 2 = match (t set), 3 = match_next (t set)
    if t > 17:
        ip += 1
        t -= 17
        if t < 4:
            state = 3
        else:
            out[op:op + t] = mv[ip:ip + t]
            op += t
            ip += t
            state = 1

    while True:
        if state == 0:
            t = mv[ip]
            ip += 1
            if t >= 16:
                state = 2
            else:
                if t == 0:
                    while mv[ip] == 0:
                        t += 255
                        ip += 1
                    t += 15 + mv[ip]
                    ip += 1
                n = t + 3
                out[op:op + n] = mv[ip:ip + n]
                op += n
                ip += n
                state = 1
                continue
        if state == 1:
            t = mv[ip]
            ip += 1
            if t >= 16:
                state = 2
            else:
                m_pos = op - (1 + M2_MAX_OFFSET)
                m_pos -= t >> 2
                m_pos -= mv[ip] << 2
                ip += 1
                op = copy_match(op, m_pos, 3)
                # match_done
                t = mv[ip - 2] & 3
                if t == 0:
                    state = 0
                    continue
                state = 3
        # match loop
        while True:
            if state == 3:
                # match_next: copy t (1..3) literals, then read next t
                out[op:op + t] = mv[ip:ip + t]
                op += t
                ip += t
                t = mv[ip]
                ip += 1
                state = 2
            # state == 2: t holds the match token
            if t >= 64:
                m_pos = op - 1
                m_pos -= (t >> 2) & 7
                m_pos -= mv[ip] << 3
                ip += 1
                t = (t >> 5) - 1
                op = copy_match(op, m_pos, t + 2)
            elif t >= 32:
                t &= 31
                if t == 0:
                    while mv[ip] == 0:
                        t += 255
                        ip += 1
                    t += 31 + mv[ip]
                    ip += 1
                m_pos = op - 1
                m_pos -= (mv[ip] >> 2) + (mv[ip + 1] << 6)
                ip += 2
                op = copy_match(op, m_pos, t + 2)
            elif t >= 16:
                m_pos = op
                m_pos -= (t & 8) << 11
                t &= 7
                if t == 0:
                    while mv[ip] == 0:
                        t += 255
                        ip += 1
                    t += 7 + mv[ip]
                    ip += 1
                m_pos -= (mv[ip] >> 2) + (mv[ip + 1] << 6)
                ip += 2
                if m_pos == op:
                    # end of stream marker
                    if op != out_len:
                        raise ValueError("LZO: output size mismatch (%d != %d)" % (op, out_len))
                    return bytes(out), ip
                m_pos -= 0x4000
                op = copy_match(op, m_pos, t + 2)
            else:
                m_pos = op - 1
                m_pos -= t >> 2
                m_pos -= mv[ip] << 2
                ip += 1
                op = copy_match(op, m_pos, 2)
            # match_done
            t = mv[ip - 2] & 3
            if t == 0:
                state = 0
                break
            state = 3
