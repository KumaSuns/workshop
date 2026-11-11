namespace MirrorDisplay;

sealed class GameAudioPanel : Control
{
    const int Blocks = 12;

    readonly Font captionFont = new("Bahnschrift", 13f, FontStyle.Bold, GraphicsUnit.Pixel);
    readonly Font valueFont = new("Bahnschrift", 28f, FontStyle.Bold, GraphicsUnit.Pixel);
    readonly Font muteFont = new("Bahnschrift", 16f, FontStyle.Bold, GraphicsUnit.Pixel);

    public int Volume { get; private set; } = 100;
    public bool Muted { get; private set; }

    public event EventHandler? OutputChanged;

    public GameAudioPanel()
    {
        Width = 104;
        Dock = DockStyle.Right;
        Cursor = Cursors.Hand;
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.UserPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
    }

    public void SetVolume(int volume)
    {
        Volume = Math.Clamp(volume, 0, 100);
        Invalidate();
        OutputChanged?.Invoke(this, EventArgs.Empty);
    }

    public void Restore(int volume, bool muted)
    {
        Volume = Math.Clamp(volume, 0, 100);
        Muted = muted;
        Invalidate();
        OutputChanged?.Invoke(this, EventArgs.Empty);
    }

    protected override void OnMouseDown(MouseEventArgs e)
    {
        base.OnMouseDown(e);
        Hit(e.Location);
    }

    protected override void OnMouseMove(MouseEventArgs e)
    {
        base.OnMouseMove(e);
        if (e.Button == MouseButtons.Left && !MuteBounds().Contains(e.Location))
        {
            SetFromMeter(e.Y);
        }
    }

    void Hit(Point point)
    {
        if (MuteBounds().Contains(point))
        {
            Muted = !Muted;
            Invalidate();
            OutputChanged?.Invoke(this, EventArgs.Empty);
            return;
        }

        if (MeterBounds().Contains(point))
        {
            SetFromMeter(point.Y);
        }
    }

    void SetFromMeter(int y)
    {
        var meter = MeterBounds();
        float t = (meter.Bottom - y) / (float)Math.Max(1, meter.Height);
        int next = (int)Math.Clamp(Math.Round(t * 100), 0, 100);
        if (next == Volume)
        {
            return;
        }

        Volume = next;
        Invalidate();
        OutputChanged?.Invoke(this, EventArgs.Empty);
    }

    Rectangle MeterBounds()
    {
        int top = 78;
        int bottom = Height - 86;
        return new Rectangle(30, top, Width - 60, Math.Max(40, bottom - top));
    }

    Rectangle MuteBounds()
    {
        return new Rectangle(10, Height - 72, Width - 20, 56);
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        var g = e.Graphics;
        g.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
        g.Clear(Color.FromArgb(8, 12, 22));

        using var edge = new Pen(Color.FromArgb(70, 80, 255, 214), 2f);
        g.DrawRectangle(edge, 1, 1, Width - 3, Height - 3);

        var accent = Muted ? Color.FromArgb(255, 84, 112) : Color.FromArgb(80, 255, 214);
        using (var caption = new SolidBrush(accent))
        {
            g.DrawString("音量", captionFont, caption, new RectangleF(0, 14, Width, 20), Centered);
        }

        using (var number = new SolidBrush(Muted ? Color.FromArgb(255, 140, 156) : Color.White))
        {
            g.DrawString(Muted ? "--" : Volume.ToString(), valueFont, number, new RectangleF(0, 36, Width, 34), Centered);
        }

        DrawMeter(g);
        DrawMute(g);
    }

    void DrawMeter(Graphics g)
    {
        var meter = MeterBounds();
        int gap = 4;
        int block = Math.Max(6, (meter.Height - gap * (Blocks - 1)) / Blocks);
        int lit = Muted ? 0 : (int)Math.Round(Volume / 100f * Blocks);
        for (int i = 0; i < Blocks; i++)
        {
            int y = meter.Bottom - (i + 1) * block - i * gap;
            var cell = new Rectangle(meter.X, y, meter.Width, block);
            bool on = i < lit;
            Color color = on ? BlockColor(i) : Color.FromArgb(26, 34, 52);
            using var brush = new SolidBrush(color);
            g.FillRectangle(brush, cell);
            if (on)
            {
                using var glow = new SolidBrush(Color.FromArgb(50, color));
                g.FillRectangle(glow, cell.X - 3, cell.Y, cell.Width + 6, cell.Height);
            }
        }
    }

    static Color BlockColor(int index)
    {
        float t = index / (float)(Blocks - 1);
        int r = (int)(80 + (255 - 80) * t);
        int green = (int)(255 + (70 - 255) * t);
        int b = (int)(214 + (170 - 214) * t);
        return Color.FromArgb(r, green, b);
    }

    void DrawMute(Graphics g)
    {
        var bounds = MuteBounds();
        var fill = Muted ? Color.FromArgb(186, 32, 64) : Color.FromArgb(16, 40, 48);
        var line = Muted ? Color.FromArgb(255, 120, 140) : Color.FromArgb(80, 255, 214);
        using var brush = new SolidBrush(fill);
        using var pen = new Pen(line, 2f);
        g.FillRectangle(brush, bounds);
        g.DrawRectangle(pen, bounds);
        using var text = new SolidBrush(Color.White);
        g.DrawString(Muted ? "消音中" : "消音", muteFont, text, bounds, Centered);
    }

    static readonly StringFormat Centered = new()
    {
        Alignment = StringAlignment.Center,
        LineAlignment = StringAlignment.Center,
    };

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            captionFont.Dispose();
            valueFont.Dispose();
            muteFont.Dispose();
        }

        base.Dispose(disposing);
    }
}
