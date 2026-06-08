-- 弹出确认框:显示对方消息 + 可编辑的草稿,返回 "按钮\t文本"
on run argv
	set theContext to item 1 of argv
	set theDraft to item 2 of argv
	try
		set theResult to display dialog theContext default answer theDraft buttons {"跳过", "发送"} default button "发送" with title "DraftMate 回复确认"
	on error
		return "跳过" & tab & ""
	end try
	return (button returned of theResult) & tab & (text returned of theResult)
end run
