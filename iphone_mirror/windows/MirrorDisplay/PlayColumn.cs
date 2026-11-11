using System.Drawing.Drawing2D;

namespace MirrorDisplay;

sealed class PlayColumn : Control
{
    const int RowHeight = 36;
    const int Gap = 8;

    static readonly string[] Lamps = { "ゲーム開始", "SKILL", "FEVER", "TIME UP" };
    static readonly string[] Rows = { "COIN", "RESULT COIN", "倍率", "コイン利益" };
    static readonly Color[] OnColors =
    {
        Color.FromArgb(48, 196, 96),
        Color.FromArgb(255, 196, 40),
        Color.FromArgb(255, 120, 32),
        Color.FromArgb(214, 22, 36),
    };

    readonly Font font = new("Yu Gothic UI", 16f, FontStyle.Bold, GraphicsUnit.Pixel);
    readonly bool[] on = new bool[Lamps.Length];
    readonly string[] values = { "", "", "", "" };

    public PlayColumn()
    {
        BackColor = Color.White;
        DoubleBuffered = true;
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.UserPaint | ControlStyles.OptimizedDoubleBuffer, true);
        Height = Lamps.Length * RowHeight + Gap + Rows.Length * RowHeight;
    }

    public void SetLamps(bool start, bool skill, bool fever, bool timeUp)
    {
        bool[] next = { start, skill, fever, timeUp };
        bool changed = false;
        for (int i = 0; i < on.Length; i++)
        {
            if (on[i] == next[i])
            {
                continue;
            }

            on[i] = next[i];
            changed = true;
        }

        if (changed)
        {
            Invalidate();
        }
    }

    public void SetMoney(string coin, string result, string rate, string profit)
    {
        string[] next = { coin, result, rate, profit };
        bool changed = false;
        for (int i = 0; i < values.Length; i++)
        {
            if (values[i] == next[i])
            {
                continue;
            }

            values[i] = next[i];
            changed = true;
        }

        if (changed)
        {
            Invalidate();
        }
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        var g = e.Graphics;
        g.Clear(Color.White);
        g.SmoothingMode = SmoothingMode.AntiAlias;
        g.TextRenderingHint = System.Drawing.Text.TextRenderingHint.ClearTypeGridFit;
        var bounds = ClientRectangle;
        bounds.Width -= 1;
        bounds.Height -= 1;
        using (var pen = new Pen(Color.FromArgb(80, 255, 214)))
        {
            g.DrawRectangle(pen, bounds);
        }

        using var text = new SolidBrush(Color.FromArgb(20, 24, 32));
        using var offFill = new SolidBrush(Color.FromArgb(214, 218, 224));
        using var offEdge = new Pen(Color.FromArgb(160, 166, 174));
        using var format = new StringFormat
        {
            Alignment = StringAlignment.Near,
            LineAlignment = StringAlignment.Center,
            Trimming = StringTrimming.EllipsisCharacter,
            FormatFlags = StringFormatFlags.NoWrap,
        };
        using var far = new StringFormat
        {
            Alignment = StringAlignment.Far,
            LineAlignment = StringAlignment.Center,
            Trimming = StringTrimming.EllipsisCharacter,
            FormatFlags = StringFormatFlags.NoWrap,
        };
        const int lamp = 14;
        for (int i = 0; i < Lamps.Length; i++)
        {
            int y = i * RowHeight;
            var circle = new Rectangle(16, y + (RowHeight - lamp) / 2, lamp, lamp);
            if (on[i])
            {
                using var fill = new SolidBrush(OnColors[i]);
                g.FillEllipse(fill, circle);
            }
            else
            {
                g.FillEllipse(offFill, circle);
                g.DrawEllipse(offEdge, circle);
            }

            var label = new RectangleF(16 + lamp + 10, y, Math.Max(1, Width - 48), RowHeight);
            g.DrawString(Lamps[i], font, text, label, format);
        }

        int top = Lamps.Length * RowHeight + Gap;
        for (int i = 0; i < Rows.Length; i++)
        {
            int y = top + i * RowHeight;
            float labelWidth = Math.Max(1, Width * 0.46f);
            g.DrawString(Rows[i], font, text, new RectangleF(16, y, labelWidth, RowHeight), format);
            g.DrawString(values[i], font, text, new RectangleF(labelWidth, y, Math.Max(1, Width - labelWidth - 16), RowHeight), far);
        }
    }
}
