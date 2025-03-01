import frappe
from frappe import _
from frappe.core.utils import get_parent_doc
from frappe.desk.doctype.todo.todo import ToDo
from frappe.email.doctype.email_account.email_account import EmailAccount
from frappe.utils import get_formatted_email, get_url, parse_addr


class CommunicationEmailMixin:
	"""Mixin class to handle communication mails."""

	def is_email_communication(self):
		return self.communication_type == "Communication" and self.communication_medium == "Email"

	def get_owner(self):
		"""Get owner of the communication docs parent."""
		parent_doc = get_parent_doc(self)
		return parent_doc.owner if parent_doc else None

	def get_all_email_addresses(self, exclude_displayname=False):
		"""Get all Email addresses mentioned in the doc along with display name."""
		return (
			self.to_list(exclude_displayname=exclude_displayname)
			+ self.cc_list(exclude_displayname=exclude_displayname)
			+ self.bcc_list(exclude_displayname=exclude_displayname)
		)

	def get_email_with_displayname(self, email_address):
		"""Returns email address after adding displayname."""
		display_name, email = parse_addr(email_address)
		if display_name and display_name != email:
			return email_address

		# emailid to emailid with display name map.
		email_map = {parse_addr(email)[1]: email for email in self.get_all_email_addresses()}
		return email_map.get(email, email)

	def mail_recipients(self, is_inbound_mail_communcation=False):
		"""Build to(recipient) list to send an email."""
		# Incase of inbound mail, recipients already received the mail, no need to send again.
		if is_inbound_mail_communcation:
			return []

		if hasattr(self, "_final_recipients"):
			return self._final_recipients

		to = self.to_list()
		self._final_recipients = list(filter(lambda id: id != "Administrator", to))
		return self._final_recipients

	def get_mail_recipients_with_displayname(self, is_inbound_mail_communcation=False):
		"""Build to(recipient) list to send an email including displayname in email."""
		to_list = self.mail_recipients(is_inbound_mail_communcation=is_inbound_mail_communcation)
		return [self.get_email_with_displayname(email) for email in to_list]

	def mail_cc(self, is_inbound_mail_communcation=False, include_sender=False):
		"""Build cc list to send an email.

		* if email copy is requested by sender, then add sender to CC.
		* If this doc is created through inbound mail, then add doc owner to cc list
		* remove all the thread_notify disabled users.
		* Make sure that all users enabled in the system
		* Remove admin from email list

		* FixMe: Removed adding TODO owners to cc list. Check if that is needed.
		"""
		if hasattr(self, "_final_cc"):
			return self._final_cc

		cc = self.cc_list()

		# Need to inform parent document owner incase communication is created through inbound mail
		if include_sender:
			cc.append(self.sender_mailid)
		if is_inbound_mail_communcation:
			cc.append(self.get_owner())
			cc = set(cc) - {self.sender_mailid}
			cc.update(self.get_assignees())

		cc = set(cc) - set(self.filter_thread_notification_disbled_users(cc))
		cc = cc - set(self.mail_recipients(is_inbound_mail_communcation=is_inbound_mail_communcation))
		cc = cc - set(self.filter_disabled_users(cc))

		# # Incase of inbound mail, to and cc already received the mail, no need to send again.
		if is_inbound_mail_communcation:
			cc = cc - set(self.cc_list() + self.to_list())

		self._final_cc = list(filter(lambda id: id != "Administrator", cc))
		return self._final_cc

	def get_mail_cc_with_displayname(self, is_inbound_mail_communcation=False, include_sender=False):
		cc_list = self.mail_cc(
			is_inbound_mail_communcation=is_inbound_mail_communcation, include_sender=include_sender
		)
		return [self.get_email_with_displayname(email) for email in cc_list if email]

	def mail_bcc(self, is_inbound_mail_communcation=False):
		"""
		* Thread_notify check
		* Email unsubscribe list
		* User must be enabled in the system
		* remove_administrator_from_email_list
		"""
		if hasattr(self, "_final_bcc"):
			return self._final_bcc

		bcc = set(self.bcc_list())
		if is_inbound_mail_communcation:
			bcc = bcc - {self.sender_mailid}
		bcc = bcc - set(self.filter_thread_notification_disbled_users(bcc))
		bcc = bcc - set(self.mail_recipients(is_inbound_mail_communcation=is_inbound_mail_communcation))
		bcc = bcc - set(self.filter_disabled_users(bcc))

		# Incase of inbound mail, to and cc & bcc already received the mail, no need to send again.
		if is_inbound_mail_communcation:
			bcc = bcc - set(self.bcc_list() + self.to_list())

		self._final_bcc = list(filter(lambda id: id != "Administrator", bcc))
		return self._final_bcc

	def get_mail_bcc_with_displayname(self, is_inbound_mail_communcation=False):
		bcc_list = self.mail_bcc(is_inbound_mail_communcation=is_inbound_mail_communcation)
		return [self.get_email_with_displayname(email) for email in bcc_list if email]

	def mail_sender(self):
		email_account = self.get_outgoing_email_account()
		if not self.sender_mailid and email_account:
			return email_account.email_id
		return self.sender_mailid

	def mail_sender_fullname(self):
		email_account = self.get_outgoing_email_account()
		if not self.sender_full_name:
			return (email_account and email_account.name) or _("Notification")
		return self.sender_full_name

	def get_mail_sender_with_displayname(self):
		return get_formatted_email(self.mail_sender_fullname(), mail=self.mail_sender())

	def get_content(self, print_format=None):
		if print_format:
			return self.content + self.get_attach_link(print_format)
		return self.content

	def get_attach_link(self, print_format):
		"""Returns public link for the attachment via `templates/emails/print_link.html`."""
		return frappe.get_template("templates/emails/print_link.html").render(
			{
				"url": get_url(),
				"doctype": self.reference_doctype,
				"name": self.reference_name,
				"print_format": print_format,
				"key": get_parent_doc(self).get_document_share_key(),
			}
		)

	def get_outgoing_email_account(self):
		if not hasattr(self, "_outgoing_email_account"):
			if self.email_account:
				self._outgoing_email_account = EmailAccount.find(self.email_account)
			else:
				self._outgoing_email_account = EmailAccount.find_outgoing(
					match_by_email=self.sender_mailid, match_by_doctype=self.reference_doctype
				)

				if self.sent_or_received == "Sent" and self._outgoing_email_account:
					self.db_set("email_account", self._outgoing_email_account.name)

		return self._outgoing_email_account

	def get_incoming_email_account(self):
		if not hasattr(self, "_incoming_email_account"):
			self._incoming_email_account = EmailAccount.find_incoming(
				match_by_email=self.sender_mailid, match_by_doctype=self.reference_doctype
			)
		return self._incoming_email_account

	def mail_attachments(self, print_format=None, print_html=None):
		final_attachments = []

		if print_format or print_html:
			d = {
				"print_format": print_format,
				"html": print_html,
				"print_format_attachment": 1,
				"doctype": self.reference_doctype,
				"name": self.reference_name,
			}
			final_attachments.append(d)

		for a in self.get_attachments() or []:
			final_attachments.append({"fid": a["name"]})

		return final_attachments

	def get_unsubscribe_message(self):
		email_account = self.get_outgoing_email_account()
		if email_account and email_account.send_unsubscribe_message:
			return _("Leave this conversation")
		return ""

	def exclude_emails_list(self, is_inbound_mail_communcation=False, include_sender=False) -> list:
		"""List of mail id's excluded while sending mail."""
		all_ids = self.get_all_email_addresses(exclude_displayname=True)

		final_ids = (
			self.mail_recipients(is_inbound_mail_communcation=is_inbound_mail_communcation)
			+ self.mail_bcc(is_inbound_mail_communcation=is_inbound_mail_communcation)
			+ self.mail_cc(
				is_inbound_mail_communcation=is_inbound_mail_communcation, include_sender=include_sender
			)
		)

		return list(set(all_ids) - set(final_ids))

	def get_assignees(self):
		"""Get owners of the reference document."""
		filters = {
			"status": "Open",
			"reference_name": self.reference_name,
			"reference_type": self.reference_doctype,
		}
		return ToDo.get_owners(filters)

	@staticmethod
	def filter_thread_notification_disbled_users(emails):
		"""Filter users based on notifications for email threads setting is disabled."""
		if not emails:
			return []

		return frappe.get_all(
			"User", pluck="email", filters={"email": ["in", emails], "thread_notify": 0}
		)

	@staticmethod
	def filter_disabled_users(emails):
		""" """
		if not emails:
			return []

		return frappe.get_all("User", pluck="email", filters={"email": ["in", emails], "enabled": 0})

	def sendmail_input_dict(
		self,
		print_html=None,
		print_format=None,
		send_me_a_copy=None,
		print_letterhead=None,
		is_inbound_mail_communcation=None,
	):

		outgoing_email_account = self.get_outgoing_email_account()
		if not outgoing_email_account:
			return {}

		recipients = self.get_mail_recipients_with_displayname(
			is_inbound_mail_communcation=is_inbound_mail_communcation
		)
		cc = self.get_mail_cc_with_displayname(
			is_inbound_mail_communcation=is_inbound_mail_communcation, include_sender=send_me_a_copy
		)
		bcc = self.get_mail_bcc_with_displayname(
			is_inbound_mail_communcation=is_inbound_mail_communcation
		)

		if not (recipients or cc):
			return {}

		final_attachments = self.mail_attachments(print_format=print_format, print_html=print_html)
		incoming_email_account = self.get_incoming_email_account()
		return {
			"recipients": recipients,
			"cc": cc,
			"bcc": bcc,
			"expose_recipients": "header",
			"sender": self.get_mail_sender_with_displayname(),
			"reply_to": incoming_email_account and incoming_email_account.email_id,
			"subject": self.subject,
			"content": self.get_content(print_format=print_format),
			"reference_doctype": self.reference_doctype,
			"reference_name": self.reference_name,
			"attachments": final_attachments,
			"message_id": self.message_id,
			"unsubscribe_message": self.get_unsubscribe_message(),
			"delayed": True,
			"communication": self.name,
			"read_receipt": self.read_receipt,
			"is_notification": (self.sent_or_received == "Received" and True) or False,
			"print_letterhead": print_letterhead,
		}

	def send_email(
		self,
		print_html=None,
		print_format=None,
		send_me_a_copy=None,
		print_letterhead=None,
		is_inbound_mail_communcation=None,
	):
		input_dict = self.sendmail_input_dict(
			print_html=print_html,
			print_format=print_format,
			send_me_a_copy=send_me_a_copy,
			print_letterhead=print_letterhead,
			is_inbound_mail_communcation=is_inbound_mail_communcation,
		)

		if input_dict:
			frappe.sendmail(**input_dict)
