using NAudio.CoreAudioApi;
using NAudio.Wave;

namespace MirrorDisplay;

sealed class PcmPlayer : IDisposable
{
    const int PrebufferMs = 200;
    const int MaxLatencyMs = 500;

    WasapiOut? output;
    BufferedWaveProvider? provider;
    readonly List<byte> pending = new();
    int rate;
    int channels;
    bool playing;
    bool decided;
    bool byteSwap;
    DateTime nextTry = DateTime.MinValue;

    public void Play(byte[] pcm, int sampleRate, int channelCount)
    {
        if (pcm.Length == 0 || channelCount < 1)
        {
            return;
        }

        int align = channelCount * 2;
        int length = pcm.Length - (pcm.Length % align);
        if (length <= 0)
        {
            return;
        }

        try
        {
            var chunk = pcm.AsSpan(0, length).ToArray();
            Note(chunk, sampleRate, channelCount);
            if (!decided)
            {
                pending.AddRange(chunk);
                if (!TryDecide(sampleRate, channelCount))
                {
                    return;
                }

                chunk = pending.ToArray();
                pending.Clear();
            }

            if (byteSwap)
            {
                Swap16(chunk);
            }

            if (!playing && IsSilence(chunk))
            {
                return;
            }

            ApplyGain(chunk);
            Submit(chunk, sampleRate, channelCount);
        }
        catch
        {
            output?.Dispose();
            output = null;
            provider = null;
            playing = false;
            nextTry = DateTime.UtcNow.AddSeconds(2);
        }
    }

    int seen;
    int maxPeak;

    void Note(byte[] pcm, int sampleRate, int channelCount)
    {
        seen++;
        int samples = pcm.Length / 2;
        for (int i = 0; i < samples; i++)
        {
            maxPeak = Math.Max(maxPeak, Math.Abs((int)Read16(pcm, i, swap: false)));
        }

        if (seen % 100 != 0)
        {
            return;
        }

        File.AppendAllText(
            Path.Combine(Path.GetTempPath(), "mirror-audio.txt"),
            $"packets={seen} rate={sampleRate} ch={channelCount} maxPeak={maxPeak}{Environment.NewLine}");
    }

    static bool IsSilence(byte[] pcm)
    {
        foreach (byte b in pcm)
        {
            if (b != 0)
            {
                return false;
            }
        }

        return true;
    }

    bool TryDecide(int sampleRate, int channelCount)
    {
        int bytesPerSecond = sampleRate * channelCount * 2;
        if (pending.Count < Math.Min(bytesPerSecond, 8192))
        {
            return false;
        }

        var data = pending.ToArray();
        int start = FirstLoudSample(data);
        if (start < 0)
        {
            if (pending.Count > sampleRate * channelCount * 2)
            {
                pending.Clear();
            }

            return false;
        }

        int measured = Math.Min(data.Length - start * 2, 8192);
        if (measured < 4096)
        {
            return false;
        }

        var slice = data.AsSpan(start * 2, measured - (measured % 2)).ToArray();
        double raw = ZeroCrossingRate(slice, swap: false);
        double swapped = ZeroCrossingRate(slice, swap: true);
        byteSwap = swapped - raw <= 0.12;
        decided = true;
        File.AppendAllText(
            Path.Combine(Path.GetTempPath(), "mirror-audio.txt"),
            $"swap={byteSwap} raw={raw:F3} swapped={swapped:F3}{Environment.NewLine}");
        return true;
    }

    static int FirstLoudSample(byte[] pcm)
    {
        int samples = pcm.Length / 2;
        for (int i = 0; i < samples; i++)
        {
            if (Math.Abs((int)Read16(pcm, i, swap: false)) > 200)
            {
                return i;
            }
        }

        return -1;
    }

    static double ZeroCrossingRate(byte[] pcm, bool swap)
    {
        int samples = pcm.Length / 2;
        if (samples < 2)
        {
            return 1;
        }

        int crossings = 0;
        short previous = Read16(pcm, 0, swap);
        for (int i = 1; i < samples; i++)
        {
            short sample = Read16(pcm, i, swap);
            if ((sample >= 0) != (previous >= 0))
            {
                crossings++;
            }

            previous = sample;
        }

        return crossings / (double)(samples - 1);
    }

    static short Read16(byte[] pcm, int index, bool swap)
    {
        int offset = index * 2;
        byte lo = swap ? pcm[offset + 1] : pcm[offset];
        byte hi = swap ? pcm[offset] : pcm[offset + 1];
        return (short)(lo | (hi << 8));
    }

    static void Swap16(byte[] pcm)
    {
        for (int i = 0; i + 1 < pcm.Length; i += 2)
        {
            (pcm[i], pcm[i + 1]) = (pcm[i + 1], pcm[i]);
        }
    }

    float volume = 1f;
    bool muted;

    public void SetOutput(float level, bool mute)
    {
        volume = Math.Clamp(level, 0f, 1f);
        muted = mute;
    }

    void ApplyGain(byte[] pcm)
    {
        float gain = muted ? 0f : volume;
        if (gain >= 0.999f)
        {
            return;
        }

        for (int i = 0; i + 1 < pcm.Length; i += 2)
        {
            short sample = (short)(pcm[i] | (pcm[i + 1] << 8));
            int scaled = (int)Math.Round(sample * gain);
            pcm[i] = (byte)(scaled & 0xff);
            pcm[i + 1] = (byte)((scaled >> 8) & 0xff);
        }
    }

    void Submit(byte[] pcm, int sampleRate, int channelCount)
    {
        if (provider == null || output == null || rate != sampleRate || channels != channelCount)
        {
            if (DateTime.UtcNow < nextTry)
            {
                return;
            }

            Restart(sampleRate, channelCount);
        }

        var buffer = provider;
        var device = output;
        if (buffer == null || device == null)
        {
            return;
        }

        buffer.AddSamples(pcm, 0, pcm.Length);
        TrimLatency();
        if (!playing && buffer.BufferedDuration.TotalMilliseconds >= PrebufferMs)
        {
            device.Play();
            playing = true;
        }
    }

    void Restart(int sampleRate, int channelCount)
    {
        output?.Dispose();
        rate = sampleRate;
        channels = channelCount;
        playing = false;
        provider = new BufferedWaveProvider(new WaveFormat(sampleRate, 16, channelCount))
        {
            DiscardOnBufferOverflow = false,
            BufferDuration = TimeSpan.FromSeconds(2),
            ReadFully = true,
        };
        output = new WasapiOut(AudioClientShareMode.Shared, false, 200);
        output.Init(provider);
    }

    void TrimLatency()
    {
        if (provider == null)
        {
            return;
        }

        var format = provider.WaveFormat;
        int maxBytes = format.AverageBytesPerSecond * MaxLatencyMs / 1000;
        maxBytes -= maxBytes % format.BlockAlign;
        int extra = provider.BufferedBytes - maxBytes;
        if (extra < format.BlockAlign)
        {
            return;
        }

        extra -= extra % format.BlockAlign;
        var junk = new byte[extra];
        provider.Read(junk, 0, extra);
    }

    public void Dispose()
    {
        output?.Dispose();
        output = null;
        provider = null;
        playing = false;
    }
}
